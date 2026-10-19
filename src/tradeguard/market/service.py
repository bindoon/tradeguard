import csv
from datetime import date
from pathlib import Path

from sqlalchemy import func, select, true
from sqlalchemy.dialects.mysql import insert

from tradeguard.db import session
from tradeguard.db.models import DailyBar, Run, Security, now
from tradeguard.market.schemas import BarInput, currency_for


def save_bars(bars: list[BarInput]) -> dict:
    if not bars:
        raise ValueError("No bars returned; empty input is not a successful sync")
    keys = [(b.symbol, b.trade_date, b.source, b.adjustment) for b in bars]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate bar keys in input")
    with session() as db, db.begin():
        securities = {b.symbol: b for b in bars}
        for symbol, b in securities.items():
            stmt = insert(Security).values(
                symbol=symbol,
                name=b.name or symbol,
                market="CN" if currency_for(symbol) == "CNY" else symbol.rsplit(".", 1)[1],
                currency=currency_for(symbol),
                industry=b.industry,
            )
            # A price-only update must not erase already-known company metadata.
            metadata = {}
            if b.name:
                metadata["name"] = stmt.inserted.name
            if b.industry:
                metadata["industry"] = stmt.inserted.industry
            db.execute(
                stmt.on_duplicate_key_update(**metadata)
                if metadata
                else stmt.on_duplicate_key_update(symbol=stmt.inserted.symbol)
            )
        for start in range(0, len(bars), 500):
            rows = [b.model_dump(exclude={"name", "industry"}) for b in bars[start : start + 500]]
            stmt = insert(DailyBar).values(rows)
            db.execute(
                stmt.on_duplicate_key_update(
                    **{
                        **{
                            k: getattr(stmt.inserted, k)
                            for k in ("open", "high", "low", "close", "volume", "amount")
                        },
                        "fetched_at": now(),
                    },
                )
            )
        details = {
            "rows": len(bars),
            "symbols": len(securities),
            "min_date": str(min(b.trade_date for b in bars)),
            "max_date": str(max(b.trade_date for b in bars)),
            "sources": sorted({b.source for b in bars}),
        }
        run = Run(kind="market_import", status="success", finished_at=now(), details=details)
        db.add(run)
        db.flush()
        return {"run_id": run.id, **details}


def import_csv(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as f:
        bars = [
            BarInput.model_validate({k: v for k, v in row.items() if v != ""})
            for row in csv.DictReader(f)
        ]
    return save_bars(bars)


def quality(target: date, source: str, adjustment: str, market: str | None = None) -> dict:
    with session() as db:
        latest = db.execute(
            select(DailyBar.symbol, func.max(DailyBar.trade_date))
            .join(Security, Security.symbol == DailyBar.symbol)
            .where(
                Security.market == market if market else true(),
                DailyBar.trade_date <= target,
                DailyBar.source == source,
                DailyBar.adjustment == adjustment,
            )
            .group_by(DailyBar.symbol)
        ).all()
    stale = [symbol for symbol, day in latest if day != target]
    return {
        "date": str(target),
        "source": source,
        "adjustment": adjustment,
        "known_symbols": len(latest),
        "current": len(latest) - len(stale),
        "stale": stale,
        "scope": "stored_symbols_only",
    }


def stats(source: str, adjustment: str = "forward", market: str | None = None) -> dict:
    with session() as db:
        count, symbols, earliest, latest = db.execute(
            select(
                func.count(),
                func.count(func.distinct(DailyBar.symbol)),
                func.min(DailyBar.trade_date),
                func.max(DailyBar.trade_date),
            )
            .join(Security, Security.symbol == DailyBar.symbol)
            .where(
                DailyBar.source == source,
                DailyBar.adjustment == adjustment,
                Security.market == market if market else true(),
            )
        ).one()
    return {
        "source": source,
        "adjustment": adjustment,
        "rows": count,
        "symbols": symbols,
        "min_date": str(earliest) if earliest else None,
        "max_date": str(latest) if latest else None,
    }
