"""One-way copy of local scan results and portfolio snapshots to the online console DB.

The online console (stock.zhiyu.hk) reads its own `tradeguard` database. This module
only ever writes there, never to the read-only selection/portfolio sources. Daily bars
are opt-in because the scope agreed with the user is scans, reports and snapshots.
The daily report is derived from scan_summary/scan_result, so copying those rows makes
`report daily` against the online DB reproduce the local report.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import Engine, create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tradeguard.config import Settings, settings
from tradeguard.db import session
from tradeguard.db.models import (
    Account,
    BarDateCoverage,
    BarSeriesCoverage,
    DailyBar,
    PortfolioSnapshot,
    Run,
    RunEvent,
    ScanResult,
    ScanSummary,
    Security,
    WatchItem,
)
from tradeguard.db.write import upsert

ONLINE_DATABASE = "tradeguard"
FORBIDDEN_DATABASES = {"stock_market", "stock_portfolio"}
BATCH = 1000


def _columns(model) -> list[str]:
    return [column.name for column in model.__table__.columns]


def _rows(db, model, *where) -> list[dict[str, Any]]:
    table = model.__table__
    return [dict(row._mapping) for row in db.execute(select(table).where(*where)).all()]


def _put(db, model, rows: list[dict[str, Any]], keys: set[str]) -> int:
    fields = [name for name in _columns(model) if name not in keys]
    for offset in range(0, len(rows), BATCH):
        db.execute(upsert(model, rows[offset : offset + BATCH], fields))
    return len(rows)


def _same_target(a: str, b: str) -> bool:
    left, right = make_url(a), make_url(b)
    return (left.host, left.port or 3306, left.database) == (
        right.host,
        right.port or 3306,
        right.database,
    )


def online_url(cfg: Settings | None = None) -> str | None:
    cfg = cfg or settings()
    if cfg.online_database_url is None:
        return None
    value = cfg.online_database_url.get_secret_value().strip()
    return value or None


def check_target(url: str, cfg: Settings | None = None) -> None:
    """Refuse anything but the dedicated online `tradeguard` runtime DB."""
    cfg = cfg or settings()
    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql":
        raise ValueError("Online sync target must be MySQL")
    if parsed.database in FORBIDDEN_DATABASES or parsed.database != ONLINE_DATABASE:
        raise ValueError(f"Online sync only writes to the `{ONLINE_DATABASE}` database")
    if _same_target(url, cfg.database_url.get_secret_value()):
        raise ValueError("Online sync target is the local runtime DB")
    for source in (
        cfg.selection_source_url,
        cfg.portfolio_source_url,
        cfg.migration_source_url,
    ):
        if source is not None and _same_target(url, source.get_secret_value()):
            raise ValueError("Online sync target is a read-only source DB")


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def ssh_tunnel(spec: str | None, url: str) -> Iterator[None]:
    """Open `ssh -L` for the sync if configured, e.g. spec `kueng:127.0.0.1:53316`.

    The local end is the host/port of the online URL, which must be loopback.
    An existing listener on that port is reused and left running.
    """
    if not spec:
        yield
        return
    host, remote_host, remote_port = spec.rsplit(":", 2)
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost"} or not parsed.port:
        raise ValueError("With an SSH tunnel the online URL must use 127.0.0.1:<port>")
    port = int(parsed.port)
    if _listening(port):
        yield
        return
    process = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-N",
            "-L",
            f"127.0.0.1:{port}:{remote_host}:{int(remote_port)}",
            host,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        while not _listening(port):
            if process.poll() is not None:
                raise RuntimeError("SSH tunnel to the online DB failed to start")
            if time.monotonic() > deadline:
                raise RuntimeError("SSH tunnel to the online DB timed out")
            time.sleep(0.2)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _scan_dates(market: str, target: date | None, start: date | None, end: date | None):
    with session() as db:
        query = select(ScanSummary.trade_date).where(ScanSummary.market == market).distinct()
        if target is not None:
            query = query.where(ScanSummary.trade_date == target)
        elif start is not None and end is not None:
            query = query.where(ScanSummary.trade_date >= start, ScanSummary.trade_date <= end)
        else:
            latest = db.scalar(
                select(func.max(ScanSummary.trade_date)).where(ScanSummary.market == market)
            )
            if latest is None:
                return []
            query = query.where(ScanSummary.trade_date == latest)
        return sorted(db.scalars(query).all())


def _sync_day(local, remote, market: str, day: date, bars: bool) -> dict[str, Any]:
    summaries = _rows(
        local, ScanSummary, ScanSummary.market == market, ScanSummary.trade_date == day
    )
    runs = _rows(local, Run, Run.kind == "scan", Run.market == market, Run.market_date == day)
    known = {row["id"] for row in runs}
    missing = sorted({row["run_id"] for row in summaries} - known)
    if missing:
        runs += _rows(local, Run, Run.id.in_(missing))
    run_ids = [row["id"] for row in runs]
    results = _rows(local, ScanResult, ScanResult.run_id.in_(run_ids)) if run_ids else []
    symbols = sorted({row["symbol"] for row in results})
    securities = _rows(local, Security, Security.symbol.in_(symbols)) if symbols else []

    stale_query = select(Run.id).where(
        Run.kind == "scan", Run.market == market, Run.market_date == day
    )
    if run_ids:
        stale_query = stale_query.where(Run.id.not_in(run_ids))
    stale = list(remote.scalars(stale_query).all())
    remote.execute(
        delete(ScanSummary).where(ScanSummary.market == market, ScanSummary.trade_date == day)
    )
    touched = run_ids + stale
    if touched:
        remote.execute(delete(ScanResult).where(ScanResult.run_id.in_(touched)))
    if stale:
        remote.execute(
            WatchItem.__table__.update()
            .where(WatchItem.scan_run_id.in_(stale))
            .values(scan_run_id=None)
        )
        remote.execute(delete(RunEvent).where(RunEvent.run_id.in_(stale)))
        remote.execute(delete(Run).where(Run.id.in_(stale)))
    _put(remote, Security, securities, {"symbol"})
    _put(remote, Run, runs, {"id"})
    _put(remote, ScanResult, results, {"run_id", "symbol"})
    _put(remote, ScanSummary, summaries, {"id"})
    out: dict[str, Any] = {
        "date": str(day),
        "scan_runs": len(runs),
        "scan_summary": len(summaries),
        "scan_result": len(results),
        "security": len(securities),
        "removed_stale_runs": len(stale),
    }
    if bars:
        out["daily_bar"] = _sync_bars(local, remote, market, day, summaries)
    return out


def _sync_bars(local, remote, market: str, day: date, summaries: list[dict]) -> int:
    count = 0
    for source, adjustment in sorted({(s["source"], s["adjustment"]) for s in summaries}):
        rows = _rows(
            local,
            DailyBar,
            DailyBar.trade_date == day,
            DailyBar.source == source,
            DailyBar.adjustment == adjustment,
        )
        symbols = sorted({row["symbol"] for row in rows})
        if not symbols:
            continue
        _put(remote, Security, _rows(local, Security, Security.symbol.in_(symbols)), {"symbol"})
        _put(
            remote,
            BarSeriesCoverage,
            _rows(
                local,
                BarSeriesCoverage,
                BarSeriesCoverage.symbol.in_(symbols),
                BarSeriesCoverage.source == source,
                BarSeriesCoverage.adjustment == adjustment,
            ),
            {"symbol", "source", "adjustment"},
        )
        count += _put(remote, DailyBar, rows, {"symbol", "trade_date", "source", "adjustment"})
        _put(
            remote,
            BarDateCoverage,
            _rows(
                local,
                BarDateCoverage,
                BarDateCoverage.market == market,
                BarDateCoverage.source == source,
                BarDateCoverage.adjustment == adjustment,
                BarDateCoverage.trade_date == day,
            ),
            {"market", "source", "adjustment", "trade_date"},
        )
    return count


def _sync_portfolio(local, remote) -> dict[str, int]:
    """Copy accounts and each account's latest snapshot (append-only, keyed by id)."""
    accounts = _rows(local, Account)
    latest = []
    for account in accounts:
        row = local.execute(
            select(PortfolioSnapshot.__table__)
            .where(PortfolioSnapshot.account_id == account["id"])
            .order_by(
                PortfolioSnapshot.as_of.desc(),
                PortfolioSnapshot.recorded_at.desc(),
                PortfolioSnapshot.id.desc(),
            )
            .limit(1)
        ).first()
        if row is not None:
            latest.append(dict(row._mapping))
    _put(remote, Account, accounts, {"id"})
    _put(remote, PortfolioSnapshot, latest, {"id"})
    return {"account": len(accounts), "portfolio_snapshot": len(latest)}


def online_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 15})


def sync_online(
    target: date | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    market: str = "CN",
    bars: bool | None = None,
    portfolio: bool = True,
    url: str | None = None,
) -> dict[str, Any]:
    if target is not None and (start is not None or end is not None):
        raise ValueError("--date cannot be combined with --from/--to")
    if (start is None) ^ (end is None):
        raise ValueError("--from and --to must be used together")
    cfg = settings()
    url = url or online_url(cfg)
    if not url:
        raise ValueError("TRADEGUARD_ONLINE_DATABASE_URL is not set")
    check_target(url, cfg)
    bars = cfg.online_sync_bars if bars is None else bars
    days = _scan_dates(market, target, start, end)
    if not days and not portfolio:
        raise ValueError("No local scan summary for the requested dates")
    with ssh_tunnel(cfg.online_ssh_tunnel, url):
        remote_engine = online_engine(url)
        try:
            with remote_engine.connect() as probe:
                if probe.scalar(text("SELECT DATABASE()")) != ONLINE_DATABASE:
                    raise ValueError(f"Online connection is not on `{ONLINE_DATABASE}`")
                with session() as local:
                    local_rev = local.scalar(text("SELECT version_num FROM alembic_version"))
                remote_rev = probe.scalar(text("SELECT version_num FROM alembic_version"))
                if remote_rev != local_rev:
                    raise ValueError(
                        f"Online schema {remote_rev} differs from local {local_rev}; "
                        "run alembic upgrade on the online DB first"
                    )
            synced = []
            with session() as local:
                for day in days:
                    with Session(remote_engine) as remote, remote.begin():
                        synced.append(_sync_day(local, remote, market, day, bars))
                portfolio_counts = None
                if portfolio:
                    with Session(remote_engine) as remote, remote.begin():
                        portfolio_counts = _sync_portfolio(local, remote)
        finally:
            remote_engine.dispose()
    return {
        "status": "success",
        "market": market,
        "target": "online:" + ONLINE_DATABASE,
        "bars": bars,
        "dates": synced,
        "portfolio": portfolio_counts,
    }


_URL = re.compile(r"//[^/@\s]+@")


def safe_error(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        orig = getattr(exc, "orig", None)
        detail = orig.args[0] if orig is not None and getattr(orig, "args", None) else ""
        return f"{type(exc).__name__} {detail}".strip()
    return _URL.sub("//***@", f"{type(exc).__name__}: {exc}")[:300]


def sync_after_pipeline(scan_dates: list[date], market: str = "CN") -> dict[str, Any] | None:
    """Best-effort hook for the daily pipeline; never raises."""
    try:
        if not online_url():
            return None
        if scan_dates:
            result = sync_online(start=min(scan_dates), end=max(scan_dates), market=market)
        else:
            result = sync_online(market=market)
        print(f"线上同步完成：{[item['date'] for item in result['dates']]}", file=sys.stderr)
        return result
    except Exception as exc:
        error = safe_error(exc)
        print(f"线上同步失败（不影响本地扫描）：{error}", file=sys.stderr)
        return {"status": "failed", "error": error}
