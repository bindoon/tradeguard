from datetime import date, timedelta
from typing import Any

from tradeguard.db import session
from tradeguard.db.locks import named_lock
from tradeguard.db.models import Run, now
from tradeguard.market.baostock import sync
from tradeguard.market.service import quality
from tradeguard.screening.service import scan


def daily(
    target: date,
    symbols: list[str] | None = None,
    source: str = "legacy_mysql",
    refresh: bool = False,
    market_code: str = "CN",
) -> dict:
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
