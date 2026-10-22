"""Read-only, resumable migration of the existing stock-scanner MySQL cache."""

import hashlib
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from pydantic import ValidationError
from sqlalchemy import text, update
from sqlalchemy.dialects.mysql import insert

from tradeguard.config import settings
from tradeguard.db import engine, session
from tradeguard.db.locks import named_lock
from tradeguard.db.models import DailyBar, Run, Security, now
from tradeguard.db.readonly import open_readonly
from tradeguard.market.schemas import BarInput, currency_for, normalize_symbol

FIELDS = [
    "symbol",
    "trade_date",
    "source",
    "adjustment",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "fetched_at",
]


def _decimal(value, places: int):
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_EVEN)


def import_mysql(
    resume_run: str | None = None,
    since: date | None = None,
    max_rows: int | None = None,
    batch_size: int = 10000,
) -> dict:
    with named_lock("legacy-import"):
        return _import_mysql(resume_run, since, max_rows, batch_size)


def _import_mysql(
    resume_run: str | None, since: date | None, max_rows: int | None, batch_size: int
) -> dict:
    cfg = settings()
    if cfg.selection_source_url is None:
        raise ValueError("Configure TRADEGUARD_SELECTION_SOURCE_URL for read-only legacy import")
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive")
    source_url = cfg.selection_source_url.get_secret_value()
    source_hash = hashlib.sha256(source_url.encode()).hexdigest()
    with session() as db, db.begin():
        run = db.get(Run, resume_run) if resume_run else None
        if resume_run and (run is None or run.kind != "legacy_import"):
            raise ValueError("Legacy import run not found")
        if run:
            if run.details["source_hash"] != source_hash:
                raise ValueError("Source configuration differs from this import run")
            if since is not None and str(since) != run.details.get("since"):
                raise ValueError("Resume must retain the original since date")
            since = date.fromisoformat(run.details["since"]) if run.details.get("since") else None
            run.status = "running"
            run.finished_at = None
        else:
            run = Run(
                kind="legacy_import",
                details={
                    "last_id": 0,
                    "rows_imported": 0,
                    "rows_skipped": 0,
                    "source_hash": source_hash,
                    "since": str(since) if since else None,
                    "source": "legacy_mysql",
                    "adjustment": "forward",
                    "provenance": "Legacy pipeline declares forward adjustment; original provider "
                    "was not stored per row. No remote writes.",
                    "invalid_examples": [],
                },
            )
            db.add(run)
        db.flush()
        run_id, progress = run.id, dict(run.details)
    source_engine = open_readonly(
        source_url, connect_args={"connect_timeout": 10, "read_timeout": 90}
    )
    invocation_rows = 0
    try:
        with source_engine.connect() as remote:
            remote.execute(text("SET SESSION TRANSACTION READ ONLY"))
            remote.commit()
            # Only cache tables are read. Never query private portfolio/credential tables here.
            securities = (
                remote.execute(text("SELECT symbol, name, industry FROM mkt_securities"))
                .mappings()
                .all()
            )
            with session() as db, db.begin():
                for s in securities:
                    symbol = normalize_symbol(s["symbol"])
                    currency = currency_for(symbol)
                    stmt = insert(Security).values(
                        symbol=symbol,
                        name=s["name"] or symbol,
                        industry=s["industry"],
                        currency=currency,
                        market="CN" if currency == "CNY" else symbol.rsplit(".", 1)[1],
                    )
                    db.execute(
                        stmt.on_duplicate_key_update(
                            name=stmt.inserted.name, industry=stmt.inserted.industry
                        )
                    )
            query = (
                "SELECT id,symbol,trade_date,open,high,low,close,volume,turnover "
                "FROM mkt_daily_bars WHERE id > :last_id"
            )
            params = {"last_id": progress["last_id"]}
            if since:
                query += " AND trade_date >= :since"
                params["since"] = since
            query += " ORDER BY id"
            if max_rows:
                query += " LIMIT :maximum"
                params["maximum"] = max_rows
            cursor = (
                remote.execution_options(stream_results=True)
                .execute(text(query), params)
                .mappings()
            )
            while batch := cursor.fetchmany(batch_size):
                valid = []
                rejected = []
                for raw in batch:
                    try:
                        b = BarInput(
                            symbol=raw["symbol"],
                            trade_date=raw["trade_date"],
                            source="legacy_mysql",
                            adjustment="forward",
                            **{k: _decimal(raw[k], 8) for k in ("open", "high", "low", "close")},
                            volume=_decimal(raw["volume"], 4),
                            amount=_decimal(raw["turnover"], 4),
                        )
                        valid.append(
                            tuple(getattr(b, k) if k != "fetched_at" else now() for k in FIELDS)
                        )
                    except (ValidationError, ValueError, ArithmeticError):
                        rejected.append({"id": int(raw["id"]), "reason": "invalid_ohlcv"})
                next_progress = {
                    **progress,
                    "last_id": int(batch[-1]["id"]),
                    "rows_imported": progress["rows_imported"] + len(valid),
                    "rows_skipped": progress["rows_skipped"] + len(rejected),
                    "invalid_examples": (progress["invalid_examples"] + rejected)[:20],
                }
                with engine().begin() as local:
                    # Some old cache symbols have no master row. Preserve them without
                    # pretending that absent company/industry metadata was supplied.
                    for cached_symbol in {str(row[0]) for row in valid}:
                        currency = currency_for(cached_symbol)
                        local.execute(
                            insert(Security)
                            .values(
                                symbol=cached_symbol,
                                name=cached_symbol,
                                market="CN"
                                if currency == "CNY"
                                else cached_symbol.rsplit(".", 1)[1],
                                currency=currency,
                            )
                            .on_duplicate_key_update(symbol=cached_symbol)
                        )
                    for offset in range(0, len(valid), 1000):
                        values = [
                            dict(zip(FIELDS, row, strict=True))
                            for row in valid[offset : offset + 1000]
                        ]
                        if values:
                            stmt = insert(DailyBar).values(values)
                            local.execute(
                                stmt.on_duplicate_key_update(
                                    **{k: getattr(stmt.inserted, k) for k in FIELDS[4:]}
                                )
                            )
                    local.execute(update(Run).where(Run.id == run_id).values(details=next_progress))
                progress = next_progress
                invocation_rows += len(batch)
            finished = not max_rows or invocation_rows < max_rows
            status = "success" if finished and not progress["rows_skipped"] else "partial"
            with session() as db, db.begin():
                saved = db.get(Run, run_id)
                assert saved is not None
                saved.status, saved.finished_at = status, now()
            return {
                "run_id": run_id,
                "status": status,
                "complete": finished,
                **{k: v for k, v in progress.items() if k != "source_hash"},
            }
    except Exception:
        with session() as db, db.begin():
            saved = db.get(Run, run_id)
            assert saved is not None
            saved.status, saved.finished_at = "failed", now()
        raise
    finally:
        source_engine.dispose()
