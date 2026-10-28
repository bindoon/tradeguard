"""Maintain small coverage summaries in the same transaction as bar imports."""

from collections import Counter
from datetime import date

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.mysql import insert

from tradeguard.db.models import BarDateCoverage, BarSeriesCoverage, DailyBar, Security


def prepare_coverage(db, rows: list[dict]) -> set[tuple]:
    """Lock affected series and identify new bars before an upsert (including retries)."""
    first_dates: dict[tuple[str, str, str], date] = {}
    keys = set()
    for row in rows:
        series = (row["symbol"], row["source"], row["adjustment"])
        first_dates[series] = min(first_dates.get(series, row["trade_date"]), row["trade_date"])
        keys.add((row["symbol"], row["trade_date"], row["source"], row["adjustment"]))
    # Every writer acquires series locks in the same order. Overlapping imports
    # cannot both count the same new key, even if they run concurrently.
    for (symbol, source, adjustment), first in sorted(first_dates.items()):
        stmt = insert(BarSeriesCoverage).values(
            symbol=symbol, source=source, adjustment=adjustment, first_date=first
        )
        db.execute(
            stmt.on_duplicate_key_update(
                first_date=func.least(BarSeriesCoverage.first_date, stmt.inserted.first_date)
            )
        )
    existing = set()
    ordered = sorted(keys)
    for offset in range(0, len(ordered), 500):
        existing.update(
            db.execute(
                select(DailyBar.symbol, DailyBar.trade_date, DailyBar.source, DailyBar.adjustment)
                .where(
                    tuple_(
                        DailyBar.symbol, DailyBar.trade_date, DailyBar.source, DailyBar.adjustment
                    ).in_(ordered[offset : offset + 500])
                )
                .with_for_update()
            ).all()
        )
    return keys - existing


def record_coverage(db, added: set[tuple]) -> None:
    if not added:
        return
    markets = dict(
        db.execute(
            select(Security.symbol, Security.market).where(
                Security.symbol.in_({key[0] for key in added})
            )
        ).all()
    )
    counts = Counter((markets[symbol], source, adj, day) for symbol, day, source, adj in added)
    for (market, source, adjustment, day), count in sorted(counts.items()):
        stmt = insert(BarDateCoverage).values(
            market=market, source=source, adjustment=adjustment, trade_date=day, bar_count=count
        )
        db.execute(
            stmt.on_duplicate_key_update(
                bar_count=BarDateCoverage.bar_count + stmt.inserted.bar_count
            )
        )


def source_coverage(db, market: str, target) -> list[dict]:
    symbols = (
        select(
            BarSeriesCoverage.source,
            BarSeriesCoverage.adjustment,
            func.count().label("symbols"),
        )
        .join(Security, Security.symbol == BarSeriesCoverage.symbol)
        .where(Security.market == market, BarSeriesCoverage.first_date <= target)
        .group_by(BarSeriesCoverage.source, BarSeriesCoverage.adjustment)
        .subquery()
    )
    rows = db.execute(
        select(
            BarDateCoverage.source,
            BarDateCoverage.adjustment,
            func.sum(BarDateCoverage.bar_count),
            symbols.c.symbols,
            func.min(BarDateCoverage.trade_date),
            func.max(BarDateCoverage.trade_date),
        )
        .join(
            symbols,
            (symbols.c.source == BarDateCoverage.source)
            & (symbols.c.adjustment == BarDateCoverage.adjustment),
        )
        .where(BarDateCoverage.market == market, BarDateCoverage.trade_date <= target)
        .group_by(BarDateCoverage.source, BarDateCoverage.adjustment, symbols.c.symbols)
        .order_by(BarDateCoverage.source, BarDateCoverage.adjustment)
    ).all()
    return [
        dict(source=s, adjustment=a, rows=int(n), symbols=sy, min_date=str(mi), max_date=str(ma))
        for s, a, n, sy, mi, ma in rows
    ]
