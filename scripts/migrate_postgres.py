"""One-time local PostgreSQL -> MySQL copy; the source is read-only and retained."""

import json
from datetime import date

from sqlalchemy import MetaData, Table, create_engine, func, select, text
from sqlalchemy.dialects.mysql import insert

from tradeguard.config import settings
from tradeguard.db import engine
from tradeguard.db.models import Base


def migrate():
    cfg = settings()
    if cfg.migration_source_url is None:
        raise ValueError("Configure TRADEGUARD_MIGRATION_SOURCE_URL")
    source = create_engine(cfg.migration_source_url.get_secret_value())
    source_metadata = MetaData()
    report = {}
    with source.connect() as remote:
        remote.execute(text("SET TRANSACTION READ ONLY"))
        for target in Base.metadata.sorted_tables:
            try:
                old = Table(target.name, source_metadata, autoload_with=remote)
            except Exception:
                if target.name == "run_event":
                    continue
                raise
            cursor = remote.execution_options(stream_results=True).execute(select(old)).mappings()
            copied = 0
            while chunk := cursor.fetchmany(1000):
                rows = [dict(r) for r in chunk]
                if target.name == "job_run":
                    for row in rows:
                        detail = row.get("details") or {}
                        row["market"] = (
                            detail.get("market")
                            if isinstance(detail.get("market"), str)
                            else (
                                "CN"
                                if row["kind"]
                                in {"scan", "daily", "market_import", "legacy_import"}
                                else None
                            )
                        )
                        row["market_date"] = (
                            date.fromisoformat(detail["date"]) if detail.get("date") else None
                        )
                statement = insert(target)
                fields = [k for k in rows[0] if k not in target.primary_key.columns]
                if not fields:
                    fields = [next(iter(target.primary_key.columns)).name]
                with engine().begin() as local:
                    local.execute(
                        statement.on_duplicate_key_update(
                            **{k: getattr(statement.inserted, k) for k in fields}
                        ),
                        rows,
                    )
                copied += len(rows)
            with engine().connect() as local:
                actual = local.scalar(select(func.count()).select_from(target))
            report[target.name] = {"source_rows": copied, "target_rows": actual}
            if actual < copied:
                raise ValueError("Row-count mismatch in " + target.name)
            print(json.dumps({"table": target.name, **report[target.name]}), flush=True)
        old_bar = source_metadata.tables["daily_bar"]
        new_bar = Base.metadata.tables["daily_bar"]
        old_sum = remote.execute(
            select(func.sum(old_bar.c.close), func.sum(old_bar.c.volume))
        ).one()
        with engine().connect() as local:
            new_sum = local.execute(
                select(func.sum(new_bar.c.close), func.sum(new_bar.c.volume))
            ).one()
        if tuple(old_sum) != tuple(new_sum):
            raise ValueError("Daily-bar numeric totals differ")
        print(
            json.dumps(
                {
                    "verified": True,
                    "checks": ["all_table_counts", "close_sum", "volume_sum"],
                    "source_retained": True,
                }
            ),
            flush=True,
        )
    source.dispose()


if __name__ == "__main__":
    try:
        migrate()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
