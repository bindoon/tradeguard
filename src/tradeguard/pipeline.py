"""Resumable CN daily pipeline: universe, bars, scan, per-day summary.

Bar coverage is computed from daily_bar. Legacy mkt_bar_sync_runs and
mkt_strategy_scan_runs are never consulted; stale running rows there are ignored.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from tradeguard.config import settings
from tradeguard.db import session
from tradeguard.db.locks import named_lock
from tradeguard.db.maintenance import retire_stale_runs
from tradeguard.db.models import DailyBar, Run, ScanSummary, now
from tradeguard.market.providers import (
    BENCHMARK_SYMBOL,
    WARMUP_DAYS,
    AkshareProvider,
    BaostockProvider,
    BarProvider,
    ProviderOutage,
    UniverseMember,
)
from tradeguard.market.service import latest_bar_date, save_bars, upsert_universe
from tradeguard.screening.service import event, scan

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE = time(16, 0)


def latest_completed_day(moment: datetime | None = None) -> date:
    local = moment.astimezone(SHANGHAI) if moment is not None else datetime.now(SHANGHAI)
    if local.tzinfo is None:
        local = local.replace(tzinfo=SHANGHAI)
    day = local.date()
    if local.time() < CLOSE:
        day -= timedelta(days=1)
    return day


def select_scan_dates(
    calendar: list[date],
    *,
    target: date | None,
    start: date | None,
    end: date | None,
    anchor: date | None,
    completed: set[date],
    force: bool,
) -> list[date]:
    """Trading days that still need a scan.

    Default mode continues after the last stored bar and skips days that already
    have a successful summary. An explicit date or range always rescans.
    """
    if not calendar:
        raise ValueError("No trading days returned for this window")
    if target is not None:
        if target not in set(calendar) and target > calendar[-1]:
            raise ValueError("Target is not a verified trading day")
        if target not in set(calendar):
            raise ValueError("Target is not a verified trading day")
        return [target]
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("--from and --to must be used together")
        if start > end:
            raise ValueError("--from must not exceed --to")
        chosen = [day for day in calendar if start <= day <= end]
        if not chosen:
            raise ValueError("No trading day in the requested range")
        return chosen
    last = calendar[-1]
    if anchor is None:
        pending = [last]
    else:
        pending = [day for day in calendar if anchor < day <= last]
        if not pending and last not in completed:
            pending = [last]
    if force:
        return pending or [last]
    missing = [day for day in pending if day not in completed]
    if missing:
        return missing
    if last not in completed:
        return [last]
    return []


def _completed_summaries(source: str, market: str = "CN") -> set[date]:
    with session() as db:
        rows = db.scalars(
            select(ScanSummary.trade_date).where(
                ScanSummary.market == market,
                ScanSummary.source == source,
                ScanSummary.status == "success",
            )
        ).all()
    return set(rows)


def _symbol_coverage(source: str, symbols: list[str]) -> dict[str, date]:
    if not symbols:
        return {}
    found: dict[str, date] = {}
    with session() as db:
        for offset in range(0, len(symbols), 500):
            chunk = symbols[offset : offset + 500]
            rows = db.execute(
                select(DailyBar.symbol, func.max(DailyBar.trade_date))
                .where(
                    DailyBar.symbol.in_(chunk),
                    DailyBar.source == source,
                    DailyBar.adjustment == "forward",
                )
                .group_by(DailyBar.symbol)
            ).all()
            found.update({symbol: day for symbol, day in rows})
    return found


def _fetch_symbol(
    provider: BarProvider, symbol: str, start: date, end: date
) -> tuple[str, list, Exception | None]:
    try:
        return symbol, provider.history(symbol, start, end), None
    except Exception as exc:
        return symbol, [], exc


def _collect(
    provider: BarProvider,
    members: list[UniverseMember],
    scan_dates: list[date],
    fetch_end: date,
    *,
    workers: int,
    run_id: str,
) -> dict[str, Any]:
    symbols = [item.symbol for item in members]
    coverage = _symbol_coverage(provider.name, symbols)
    warmup_start = (min(scan_dates) if scan_dates else fetch_end) - timedelta(days=WARMUP_DAYS)
    todo: list[tuple[str, date]] = []
    for symbol in symbols:
        have = coverage.get(symbol)
        if have is not None and have >= fetch_end:
            continue
        start = have + timedelta(days=1) if have is not None else warmup_start
        if start <= fetch_end:
            todo.append((symbol, start))
    event(
        run_id,
        "bars",
        f"{provider.name} 需补 {len(todo)} 个标的，截至 {fetch_end}；已有最新行情的标的跳过。",
        0,
        len(todo),
    )
    failed: list[dict[str, str]] = []
    rows = 0
    outages = 0
    saved_symbols = 0
    pool_workers = 1 if provider.name == "baostock" else max(1, workers)

    def persist(symbol: str, bars: list, error: Exception | None) -> None:
        nonlocal rows, outages, saved_symbols
        if isinstance(error, ProviderOutage):
            outages += 1
            failed.append({"symbol": symbol, "reason": "provider_outage"})
            if saved_symbols == 0 and outages >= 3:
                raise error
            return
        if error is not None:
            failed.append({"symbol": symbol, "reason": type(error).__name__})
            return
        if not bars:
            failed.append({"symbol": symbol, "reason": "no_bars"})
            return
        saved = save_bars(bars, record_run=False)
        rows += int(saved["rows"])
        saved_symbols += 1

    if pool_workers == 1:
        for index, (symbol, start) in enumerate(todo, start=1):
            symbol, bars, error = _fetch_symbol(provider, symbol, start, fetch_end)
            persist(symbol, bars, error)
            if index % 100 == 0 or index == len(todo):
                event(
                    run_id, "bars", f"{provider.name} 已处理 {index}/{len(todo)}", index, len(todo)
                )
    else:
        with ThreadPoolExecutor(max_workers=pool_workers, thread_name_prefix="akshare") as pool:
            futures = {
                pool.submit(_fetch_symbol, provider, symbol, start, fetch_end): symbol
                for symbol, start in todo
            }
            done = 0
            for future in as_completed(futures):
                symbol, bars, error = future.result()
                try:
                    persist(symbol, bars, error)
                except ProviderOutage:
                    for pending in futures:
                        pending.cancel()
                    raise
                done += 1
                if done % 100 == 0 or done == len(todo):
                    event(
                        run_id,
                        "bars",
                        f"{provider.name} 已处理 {done}/{len(todo)}",
                        done,
                        len(todo),
                    )
    return {"rows": rows, "failed": failed, "fetched_symbols": len(todo), "source": provider.name}


def _run_provider(
    provider: BarProvider,
    *,
    horizon_start: date,
    horizon_end: date,
    target: date | None,
    start: date | None,
    end: date | None,
    anchor: date | None,
    force: bool,
    symbols: list[str] | None,
    workers: int,
    run_id: str,
) -> dict[str, Any]:
    with provider:
        calendar = provider.trading_days(horizon_start, horizon_end)
        calendar = [day for day in calendar if day <= horizon_end]
        if not calendar:
            raise ProviderOutage(f"{provider.name} returned no trading days")
        scan_dates = select_scan_dates(
            calendar,
            target=target,
            start=start,
            end=end,
            anchor=anchor,
            completed=_completed_summaries(provider.name),
            force=force,
        )
        as_of = scan_dates[-1] if scan_dates else calendar[-1]
        members = provider.universe(as_of)
        if symbols:
            wanted = set(symbols)
            members = [item for item in members if item.symbol in wanted]
            if len(members) != len(wanted):
                missing = sorted(wanted - {item.symbol for item in members})
                raise ValueError(f"Symbols are not in the A-share universe: {', '.join(missing)}")
        if not any(item.symbol == BENCHMARK_SYMBOL for item in members):
            members.append(
                UniverseMember(
                    symbol=BENCHMARK_SYMBOL,
                    name="上证指数",
                    sector="指数",
                    industry="指数",
                    security_kind="index",
                )
            )
        upsert_universe(members, market="CN")
        event(
            run_id,
            "universe",
            f"{provider.name} 股票池 {sum(item.security_kind != 'index' for item in members)} 只，"
            f"含 ST 标记、上市日期与行业。",
            len(members),
            len(members),
        )
        fetched = _collect(
            provider,
            members,
            scan_dates,
            as_of,
            workers=workers,
            run_id=run_id,
        )
        warnings = list(getattr(provider, "warnings", []))
        return {
            "source": provider.name,
            "calendar_end": str(calendar[-1]),
            "scan_dates": [str(day) for day in scan_dates],
            "warnings": warnings,
            **fetched,
            "_scan_dates": scan_dates,
            "_stocks": [item.symbol for item in members if item.security_kind != "index"],
        }


def run_cn_pipeline(
    *,
    target: date | None = None,
    start: date | None = None,
    end: date | None = None,
    symbols: list[str] | None = None,
    primary: BarProvider | None = None,
    fallback: BarProvider | None = None,
    allow_fallback: bool = True,
    workers: int | None = None,
    min_interval: float | None = None,
    now_local: datetime | None = None,
) -> dict[str, Any]:
    if target is not None and (start is not None or end is not None):
        raise ValueError("--date cannot be combined with --from/--to")
    if (start is None) ^ (end is None):
        raise ValueError("--from and --to must be used together")
    cfg = settings()
    worker_count = cfg.akshare_workers if workers is None else workers
    interval = cfg.akshare_min_interval if min_interval is None else min_interval
    primary = primary or AkshareProvider(min_interval=interval)
    if allow_fallback and fallback is None:
        fallback = BaostockProvider()
    force = target is not None or start is not None
    completed_through = end or target or latest_completed_day(now_local)
    anchor = latest_bar_date("CN")
    horizon_end = completed_through
    horizon_start = (start or anchor or horizon_end) - timedelta(days=WARMUP_DAYS + 30)
    retire_stale_runs()
    with named_lock("daily:CN"):
        with session() as db, db.begin():
            run = Run(
                kind="daily",
                market="CN",
                market_date=target or end or completed_through,
                details={
                    "market": "CN",
                    "requested_source": primary.name,
                    "date": str(target) if target else None,
                    "from": str(start) if start else None,
                    "to": str(end) if end else None,
                },
            )
            db.add(run)
            db.flush()
            run_id = run.id
        try:
            switched: dict[str, str] | None = None
            try:
                collected = _run_provider(
                    primary,
                    horizon_start=horizon_start,
                    horizon_end=horizon_end,
                    target=target,
                    start=start,
                    end=end,
                    anchor=anchor,
                    force=force,
                    symbols=symbols,
                    workers=worker_count,
                    run_id=run_id,
                )
            except ProviderOutage as exc:
                if not allow_fallback or fallback is None:
                    raise
                switched = {
                    "from": primary.name,
                    "to": fallback.name,
                    "reason": str(exc),
                }
                message = (
                    f"数据源从 {primary.name} 切换到 {fallback.name}，原因：{exc}。"
                    "本次扫描只使用切换后的来源，不混用价格。"
                )
                event(run_id, "source_fallback", message)
                print(message, file=sys.stderr)
                collected = _run_provider(
                    fallback,
                    horizon_start=horizon_start,
                    horizon_end=horizon_end,
                    target=target,
                    start=start,
                    end=end,
                    anchor=anchor,
                    force=force,
                    symbols=symbols,
                    workers=1,
                    run_id=run_id,
                )
            source = str(collected["source"])
            scan_dates: list[date] = collected.pop("_scan_dates")
            stocks: list[str] = collected.pop("_stocks")
            scans = []
            for day in scan_dates:
                result = scan(day, source, symbols=stocks, market="CN")
                scans.append(
                    {
                        "date": str(day),
                        "run_id": result["run_id"],
                        "status": result["status"],
                        "candidate_count": result.get("candidate_count"),
                        "resonance_count": result.get("resonance_count"),
                        "market_regime": result.get("market_regime"),
                    }
                )
            status = (
                "partial"
                if collected["failed"] or any(item["status"] != "success" for item in scans)
                else "success"
            )
            if not scan_dates and not collected["failed"]:
                status = "success"
            payload: dict[str, Any] = {
                "status": status,
                "market": "CN",
                "source": source,
                "fallback": switched,
                "anchor": str(anchor) if anchor else None,
                "fetch_end": collected.get("calendar_end"),
                "rows": collected["rows"],
                "failed": collected["failed"],
                "fetched_symbols": collected["fetched_symbols"],
                "warnings": collected.get("warnings", []),
                "scan_dates": [str(day) for day in scan_dates],
                "scans": scans,
                "up_to_date": not scan_dates and not collected["fetched_symbols"],
            }
            with session() as db, db.begin():
                row = db.get(Run, run_id)
                assert row is not None
                row.status = status
                row.finished_at = now()
                row.market_date = scan_dates[-1] if scan_dates else row.market_date
                row.details = payload
            event(
                run_id,
                "complete",
                f"每日流水线结束，来源 {source}，扫描 {len(scan_dates)} 个交易日，状态 {status}。",
            )
            return {"run_id": run_id, **payload}
        except Exception as exc:
            with session() as db, db.begin():
                row = db.get(Run, run_id)
                if row is not None:
                    row.status = "failed"
                    row.finished_at = now()
                    row.details = {
                        **(row.details or {}),
                        "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                    }
            event(run_id, "failed", "每日流水线未完成。")
            raise
