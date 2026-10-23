"""Read-only cache availability for the local scan console."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from tradeguard.db import session
from tradeguard.db.models import DailyBar, Run, Security, now


def today() -> date:
    return now().astimezone(ZoneInfo("Asia/Shanghai")).date()


def bounded_day(target: date | None = None) -> date:
    current = today()
    if target and target > current:
        raise ValueError("不能使用未来交易日")
    return target or current


def cached_equities(market: str, source: str, adjustment: str):
    return (
        select(DailyBar.trade_date)
        .join(Security, Security.symbol == DailyBar.symbol)
        .where(
            Security.market == market,
            Security.security_kind != "index",
            DailyBar.source == source,
            DailyBar.adjustment == adjustment,
            DailyBar.trade_date <= today(),
        )
    )


def cached_dates(market: str, source: str, adjustment: str) -> list[dict]:
    with session() as db:
        rows = db.execute(
            cached_equities(market, source, adjustment)
            .add_columns(func.count())
            .group_by(DailyBar.trade_date)
            .order_by(DailyBar.trade_date.desc())
        ).all()
    return [{"date": str(day), "symbols": count} for day, count in rows]


def has_cached_equities(
    target: date, market: str, source: str, adjustment: str, symbols: list[str] | None = None
) -> bool:
    query = cached_equities(market, source, adjustment).where(DailyBar.trade_date == target)
    if symbols:
        query = query.where(DailyBar.symbol.in_(symbols))
    with session() as db:
        return db.scalar(query.limit(1)) is not None


def source_activity(db, market: str) -> dict[tuple[str, str], dict]:
    source = Run.details["source"].as_string()
    adjustment = func.coalesce(Run.details["adjustment"].as_string(), "forward")
    rows = db.execute(
        select(source, adjustment, func.count(), func.max(Run.market_date))
        .where(
            Run.kind == "scan",
            Run.market == market,
            Run.status.in_(["success", "partial"]),
            Run.market_date <= today(),
        )
        .group_by(source, adjustment)
    ).all()
    return {
        (src, adj): {"scan_count": count, "latest_scan_date": str(day)}
        for src, adj, count, day in rows
    }


def preferred_source(sources: list[dict]) -> dict | None:
    # Prefer an existing scan by trade date, then fresh cache with the widest coverage.
    return max(
        sources,
        key=lambda s: (
            s.get("latest_scan_date") or "",
            s["max_date"],
            s["symbols"],
            s["adjustment"] == "forward",
            s["source"],
        ),
        default=None,
    )
