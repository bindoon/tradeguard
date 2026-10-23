from collections import Counter, defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from tradeguard.db import session
from tradeguard.db.models import DailyBar, Security, now
from tradeguard.screening.filters import FilterOptions, rejection


def filter_pool(
    market: str, source: str, target: date | None, options: dict, adjustment: str = "forward"
):
    if market not in {"CN", "US", "HK"}:
        raise ValueError("Unknown market")
    today = now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    if target and target > today:
        raise ValueError("Cannot filter a future trading day")
    config = FilterOptions.for_market(market, options)
    with session() as db:
        if target is None:
            target = db.scalar(
                select(func.max(DailyBar.trade_date))
                .join(Security, DailyBar.symbol == Security.symbol)
                .where(
                    Security.market == market,
                    DailyBar.source == source,
                    DailyBar.adjustment == adjustment,
                    DailyBar.trade_date <= today,
                )
            )
        securities = db.scalars(
            select(Security).where(Security.market == market).order_by(Security.symbol)
        ).all()
    if target is None:
        return {"total": 0, "stocks": [], "date": None, "warnings": ["当前市场没有缓存行情"]}
    kept = []
    reasons: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    fields = ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]
    for start in range(0, len(securities), 64):
        batch = securities[start : start + 64]
        with session() as db:
            bars = (
                db.execute(
                    select(*(getattr(DailyBar, k) for k in fields))
                    .where(
                        DailyBar.symbol.in_([s.symbol for s in batch]),
                        DailyBar.source == source,
                        DailyBar.adjustment == adjustment,
                        DailyBar.trade_date <= target,
                    )
                    .order_by(DailyBar.symbol, DailyBar.trade_date)
                )
                .mappings()
                .all()
            )
        grouped = defaultdict(list)
        for b in bars:
            grouped[b["symbol"]].append(dict(b))
        for s in batch:
            why, notices = rejection(s, grouped[s.symbol][-400:], target, market, config)
            warnings.update(notices)
            if why:
                reasons[why] += 1
            else:
                kept.append({"code": s.symbol, "name": s.name, "industry": s.industry or "未知"})
    return {
        "total": len(kept),
        "stocks": kept,
        "date": str(target),
        "filter_counts": dict(reasons),
        "warnings": dict(warnings),
    }
