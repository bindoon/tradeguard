import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_legacy import Result
from test_legacy import Source as BarSource

from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import Run, ScanResult, Security
from tradeguard.screening import legacy


class Source(BarSource):
    invalid = False

    def execute(self, query, params=None):
        sql = str(query)
        if sql == "SET SESSION TRANSACTION READ ONLY":
            self.readonly = True
            return Result([])
        assert self.readonly and sql.startswith("SELECT ")
        if "FROM mkt_strategy_scan_runs" in sql:
            return Result(
                [
                    {
                        "id": index,
                        "market": "CN",
                        "scan_date": target,
                        "started_at": datetime(2025, 6, 20, 8),
                        "finished_at": datetime(2025, 6, 20, 9),
                        "status": status,
                        "tradable_count": 3,
                        "candidate_count": 2,
                        "market_regime": "neutral",
                        "message": json.dumps(
                            {
                                "strategy_hit_counts": {
                                    "box_breakout": 2,
                                    "rsi_rebound": 1,
                                    "ma_golden_cross": 0,
                                }
                            }
                        ),
                    }
                    for index, status, target in [
                        (1, "running", "2025-06-19"),
                        (2, "success", "2025-06-20"),
                        (3, "success", "2099-01-01"),
                    ]
                    if params["market"] == "CN"
                ]
            )
        assert "FROM mkt_strategy_scan_results" in sql
        return Result(
            [
                {
                    "symbol": symbol,
                    "name": "Historical name",
                    "industry": "Historical industry",
                    "latest_price": price,
                    "resonance_count": len(hits),
                    "strategies_hit": json.dumps(hits),
                    "sector_strength": 0.0,
                }
                for symbol, price, hits in [
                    (
                        "600000.SH",
                        "invalid" if self.invalid else "10.12345678",
                        ["box_breakout", "rsi_rebound"],
                    ),
                    ("600001.SH", "11", ["box_breakout"]),
                    ("600002.SH", None, []),
                ]
            ]
        )


def test_import_preserves_history_and_counts_actual_hits_idempotently(database, monkeypatch):
    source = Source()
    monkeypatch.setenv("TRADEGUARD_SELECTION_SOURCE_URL", "mysql+pymysql://fixture/legacy")
    monkeypatch.setattr(legacy, "open_readonly", lambda *args, **kwargs: source)
    with session() as db, db.begin():
        db.add(
            Security(
                symbol="600000.SH",
                name="Current name",
                industry="Current industry",
                market="CN",
                currency="CNY",
            )
        )
    result = legacy.import_scans()
    assert result["imported_runs"] == 1 and result["imported_hit_stocks"] == 2
    assert result["ignored_incomplete_or_future_runs"] == 2
    assert legacy.import_scans()["existing_runs"] == 1
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 1
        assert db.scalar(select(func.count()).select_from(ScanResult)) == 2
        run = db.scalars(select(Run)).one()
        assert run.started_at == datetime(2025, 6, 20, 8, tzinfo=timezone.utc)
        assert run.details["legacy_reported_candidate_count"] == 2
        assert run.details["resonance_count"] == 1 and run.details["market_regime"] == "unknown"
        assert "ma_golden_cross" in run.details["strategies"]
        assert run.details["strategy_hit_counts"]["ma_golden_cross"] == 0
        assert db.get(Security, "600000.SH").name == "Current name"
        hit = db.get(ScanResult, (run.id, "600000.SH"))
        assert hit.close == Decimal("10.12345678")
        assert hit.metadata_snapshot["name"] == "Historical name" and hit.sector_strength is None
    summary = (
        TestClient(create_app()).get("/api/scan/summaries?market=CN&source=legacy_mysql").json()[0]
    )
    assert summary["hitStockCount"] == 2 and summary["candidateCount"] == 1
    assert summary["totalStockCount"] is None and summary["filteredOutCount"] is None
    assert summary["sectorCount"] is None
    assert summary["recordOrigin"] == "legacy_scan_cache"


def test_bad_legacy_result_does_not_publish_a_partial_scan(database, monkeypatch):
    source = Source()
    source.invalid = True
    monkeypatch.setenv("TRADEGUARD_SELECTION_SOURCE_URL", "mysql+pymysql://fixture/legacy")
    monkeypatch.setattr(legacy, "open_readonly", lambda *args, **kwargs: source)
    with pytest.raises(ValueError, match="no partial run"):
        legacy.import_scans()
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 0
        assert db.scalar(select(func.count()).select_from(ScanResult)) == 0


def test_missing_legacy_rows_do_not_become_an_empty_success(database, monkeypatch):
    class EmptySource(Source):
        def execute(self, query, params=None):
            if "FROM mkt_strategy_scan_results" in str(query):
                assert self.readonly
                return Result([])
            return super().execute(query, params)

    monkeypatch.setenv("TRADEGUARD_SELECTION_SOURCE_URL", "mysql+pymysql://fixture/legacy")
    monkeypatch.setattr(legacy, "open_readonly", lambda *args, **kwargs: EmptySource())
    with pytest.raises(ValueError, match="Incomplete legacy scan"):
        legacy.import_scans()
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 0
