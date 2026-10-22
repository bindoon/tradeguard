from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.locks import named_lock
from tradeguard.db.maintenance import retire_stale_runs
from tradeguard.db.models import DailyBar, Run, Security, now
from tradeguard.market.baostock import sync
from tradeguard.market.service import quality
from tradeguard.screening.service import scan


def cached_trade_dates(market_code: str, source: str, start: date, end: date) -> list[date]:
    with session() as db:
        return list(
            db.scalars(
                select(DailyBar.trade_date)
                .join(Security, Security.symbol == DailyBar.symbol)
                .where(
                    Security.market == market_code,
                    DailyBar.source == source,
                    DailyBar.adjustment == "forward",
                    DailyBar.trade_date >= start,
                    DailyBar.trade_date <= end,
                )
                .distinct()
                .order_by(DailyBar.trade_date)
            ).all()
        )


def run_cn_pipeline(**kwargs: Any) -> dict:
    """Akshare-first A-share backfill and scan. Tests patch this attribute."""
    from tradeguard.pipeline import run_cn_pipeline as impl

    return impl(**kwargs)


def daily(
    target: date | None = None,
    symbols: list[str] | None = None,
    source: str = "legacy_mysql",
    refresh: bool = False,
    market_code: str = "CN",
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    retire_stale_runs()
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("--from and --to must be used together")
        if refresh:
            raise ValueError("Cached ranges do not download. Omit --source to backfill CN")
        days = cached_trade_dates(market_code, source, start, end)
        if not days:
            raise ValueError("No cached bars in that range")
        scans = [daily(day, symbols, source, False, market_code) for day in days]
        status = "partial" if any(item["status"] != "success" for item in scans) else "success"
        return {"status": status, "market": market_code, "source": source, "scans": scans}
    if target is None:
        raise ValueError("Cached daily runs require --date or --from/--to")
    if market_code not in {"CN", "US", "HK"}:
        raise ValueError("market must be CN, US or HK")
    if refresh and source not in {"baostock", "longbridge"}:
        raise ValueError("Network refresh requires explicit source=baostock or longbridge")
    with named_lock("daily:" + market_code):
        try:
            with session() as db, db.begin():
                run = Run(
                    kind="daily",
                    market=market_code,
                    market_date=target,
                    details={"date": str(target), "market_code": market_code},
                )
                db.add(run)
                db.flush()
                run_id = run.id
            try:
                # Cache is the default; remote full-universe work must be explicit.
                if refresh:
                    if source == "baostock" and market_code == "CN":
                        market = sync(target, target - timedelta(days=550), symbols)
                    elif source == "longbridge":
                        from tradeguard.market.longbridge import sync as longbridge_sync

                        market = longbridge_sync(
                            target, target - timedelta(days=550), symbols, market_code
                        )
                    else:
                        raise ValueError("baostock supports CN only")
                else:
                    market = quality(target, source, "forward", market_code)
                result: dict[str, Any]
                if (refresh and market["status"] != "success") or (
                    not refresh and not market["current"]
                ):
                    result = {
                        "status": "partial",
                        "market": market,
                        "scan": None,
                        "reason": "market_quality_gate",
                    }
                else:
                    result = {
                        "status": "success",
                        "market": market,
                        "scan": scan(target, source, symbols=symbols, market=market_code),
                    }
                    result["status"] = result["scan"]["status"]
                with session() as db, db.begin():
                    row = db.get(Run, run_id)
                    assert row is not None
                    row.status, row.finished_at, row.details = result["status"], now(), result
                return {"run_id": run_id, **result}
            except Exception as exc:
                with session() as db, db.begin():
                    row = db.get(Run, run_id)
                    assert row is not None
                    row.status, row.finished_at = "failed", now()
                    row.details = {"date": str(target), "error": type(exc).__name__}
                raise
        finally:
            pass
