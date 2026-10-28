"""Import saved legacy scan observations; never run a new scan or write the source."""

import hashlib
import json
from collections import Counter
from datetime import date, timezone
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.engine import make_url

from tradeguard.config import settings
from tradeguard.db import session
from tradeguard.db.locks import named_lock
from tradeguard.db.models import Run, ScanResult, Security
from tradeguard.db.readonly import open_readonly
from tradeguard.market.schemas import currency_for, normalize_symbol
from tradeguard.screening.availability import today


def _save(source_run, source_results, source_identity):
    target = date.fromisoformat(source_run["scan_date"])
    identifier = str(
        uuid5(NAMESPACE_URL, f"tradeguard:legacy-scan:{source_identity}:{source_run['id']}")
    )
    with session() as db:
        if db.get(Run, identifier):
            return False, 0
    if source_run["tradable_count"] is not None and source_run["tradable_count"] != len(
        source_results
    ):
        raise ValueError("Incomplete legacy scan result set; no partial run was saved")
    parsed = []
    counts: Counter[str] = Counter()
    for raw in source_results:
        symbol = normalize_symbol(raw["symbol"])
        if currency_for(symbol) != {"CN": "CNY", "US": "USD", "HK": "HKD"}[source_run["market"]]:
            raise ValueError("Legacy scan result does not belong to its declared market")
        hits = json.loads(raw["strategies_hit"])
        if not isinstance(hits, list) or any(
            not isinstance(item, str) or not item for item in hits
        ):
            raise ValueError("Invalid legacy strategy list; no partial run was saved")
        hits = list(dict.fromkeys(hits))
        if not hits:
            continue
        try:
            price = Decimal(str(raw["latest_price"]))
        except InvalidOperation as exc:
            raise ValueError("Invalid legacy scan price; no partial run was saved") from exc
        if not price.is_finite() or price <= 0:
            raise ValueError("Invalid legacy scan price; no partial run was saved")
        counts.update(hits)
        parsed.append((symbol, raw, hits, price))
    original = json.loads(source_run["message"] or "{}")
    if not isinstance(original, dict):
        raise ValueError("Invalid legacy scan summary")
    recorded_counts = original.get("strategy_hit_counts") or {}
    if not isinstance(recorded_counts, dict):
        raise ValueError("Invalid legacy strategy counters")
    strategies = list(dict.fromkeys([*recorded_counts, *counts]))
    started = source_run["started_at"]
    finished = source_run["finished_at"]
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)  # Original writer uses utcnow().
    if finished is not None and finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    details = {
        "date": str(target),
        "source": "legacy_mysql",
        "adjustment": "forward",
        "record_origin": "legacy_scan_cache",
        "scanned_count": source_run["tradable_count"],
        "universe": None,
        "filtered_out_count": None,
        "resonance_count": sum(len(hits) >= 2 for _, _, hits, _ in parsed),
        "strategy_hit_counts": {name: counts[name] for name in strategies},
        "strategies": strategies,
        "market_regime": "unknown",
        "sector_strength": {},
        "legacy_source_run_id": source_run["id"],
        "legacy_reported_candidate_count": source_run["candidate_count"],
        "legacy_reported_market_regime": source_run["market_regime"],
        "legacy_summary": original,
        "provenance": "Read-only mkt_strategy_scan_runs/results import. Same legacy cache declares forward adjustment; original provider is not relabelled.",
        "data_warnings": [
            "旧记录未保存初筛总量、过滤配置和可核验的基准证据，相关项保持未知；命中与共振按逐股策略重新计数。"
        ],
    }
    with session() as db, db.begin():
        if db.get(Run, identifier):
            return False, 0
        db.add(
            Run(
                id=identifier,
                kind="scan",
                market=source_run["market"],
                market_date=target,
                status="success",
                started_at=started,
                finished_at=finished,
                details=details,
            )
        )
        db.flush()
        for symbol, raw, hits, price in parsed:
            if db.get(Security, symbol) is None:
                db.add(
                    Security(
                        symbol=symbol,
                        name=raw["name"] or symbol,
                        industry=raw["industry"],
                        market=source_run["market"],
                        currency=currency_for(symbol),
                    )
                )
                db.flush()
            db.add(
                ScanResult(
                    run_id=identifier,
                    symbol=symbol,
                    trade_date=target,
                    hits=hits,
                    resonance_count=len(hits),
                    close=price,
                    sector_strength=None,
                    metadata_snapshot={
                        "name": raw["name"],
                        "industry": raw["industry"],
                        "sector_strength": None,
                        "record_origin": "legacy_scan_cache",
                        "legacy_reported_sector_strength": str(raw["sector_strength"])
                        if raw["sector_strength"] is not None
                        else None,
                    },
                )
            )
    return True, len(parsed)


def import_scans(market: str = "CN") -> dict:
    if market not in {"CN", "US", "HK"}:
        raise ValueError("market must be CN, US or HK")
    configured = settings().selection_source_url
    if configured is None:
        raise ValueError("Configure TRADEGUARD_SELECTION_SOURCE_URL for read-only scan import")
    url = make_url(configured.get_secret_value())
    identity = hashlib.sha256(
        f"{url.drivername}:{url.host}:{url.port}/{url.database}".encode()
    ).hexdigest()
    imported = existing = ignored = hits = 0
    with named_lock("legacy-scan-import"):
        source = open_readonly(
            configured.get_secret_value(), connect_args={"connect_timeout": 10, "read_timeout": 90}
        )
        try:
            with source.connect() as remote:
                remote.execute(text("SET SESSION TRANSACTION READ ONLY"))
                remote.commit()
                runs = (
                    remote.execute(
                        text(
                            "SELECT id,market,scan_date,started_at,finished_at,status,tradable_count,"
                            "candidate_count,market_regime,message FROM mkt_strategy_scan_runs WHERE market=:market"
                        ),
                        {"market": market},
                    )
                    .mappings()
                    .all()
                )
                for row in runs:
                    if row["status"] != "success" or date.fromisoformat(row["scan_date"]) > today():
                        ignored += 1
                        continue
                    rows = (
                        remote.execute(
                            text(
                                "SELECT symbol,name,industry,latest_price,resonance_count,strategies_hit,"
                                "sector_strength FROM mkt_strategy_scan_results WHERE scan_run_id=:run_id"
                            ),
                            {"run_id": row["id"]},
                        )
                        .mappings()
                        .all()
                    )
                    saved, count = _save(row, rows, identity)
                    imported += int(saved)
                    existing += int(not saved)
                    hits += count
        finally:
            source.dispose()
    return {
        "status": "success",
        "imported_runs": imported,
        "existing_runs": existing,
        "ignored_incomplete_or_future_runs": ignored,
        "imported_hit_stocks": hits,
    }
