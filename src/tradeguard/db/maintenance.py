"""Job bookkeeping that belongs to TradeGuard, not to the legacy cache."""

from datetime import timedelta

from sqlalchemy import select

from tradeguard.config import settings
from tradeguard.db import session
from tradeguard.db.models import Run, now

# Legacy mkt_bar_sync_runs / mkt_strategy_scan_runs are often left at status=running.
# They are not a lock. Coverage comes from daily_bar; liveness comes from job_run.
ABANDONED_LEGACY_STATUSES = frozenset({"running", "pending"})


def legacy_run_is_in_progress(status: str | None) -> bool:
    """Legacy mkt_bar_sync_runs / mkt_strategy_scan_runs are not a live lock.

    Rows left at status=running are abandoned. TradeGuard resumes from daily_bar
    and its own job_run table instead of those rows.
    """
    return False


def legacy_run_filter_sql() -> str:
    """SQL predicate that drops abandoned legacy run rows if those tables are read."""
    quoted = ", ".join(f"'{item}'" for item in sorted(ABANDONED_LEGACY_STATUSES))
    return f"status NOT IN ({quoted})"


def retire_stale_runs(timeout: timedelta | None = None) -> list[str]:
    """Mark job_run rows that never finished as stale so a new run can proceed."""
    seconds = settings().job_stale_seconds if timeout is None else int(timeout.total_seconds())
    cutoff = now() - timedelta(seconds=seconds)
    with session() as db, db.begin():
        rows = db.scalars(
            select(Run).where(
                Run.status.in_(("running", "queued")),
                Run.started_at < cutoff,
            )
        ).all()
        retired: list[str] = []
        for row in rows:
            row.status = "stale"
            row.finished_at = now()
            row.details = {
                **(row.details or {}),
                "stale_reason": "timeout",
                "stale_after_seconds": seconds,
            }
            retired.append(row.id)
        return retired
