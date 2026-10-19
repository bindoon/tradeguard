from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_discipline import inputs

from tradeguard.console import create_app
from tradeguard.db.models import now
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import import_csv, save_bars
from tradeguard.portfolio.schemas import ManualPatch, Position, StopOrder
from tradeguard.portfolio.service import latest, manual_update, save_snapshot
from tradeguard.screening.service import scan


def test_console_market_isolation_and_historical_chart(database):
    imported = import_csv(Path("examples/bars.csv"))
    day = date.fromisoformat(imported["max_date"])
    save_bars(
        [
            BarInput(
                symbol="AAPL.US",
                trade_date=day,
                source="fixture",
                adjustment="forward",
                open="10",
                high="11",
                low="9",
                close="10",
                volume="100",
            )
        ]
    )
    result = scan(day, "synthetic")
    client = TestClient(create_app())
    assert client.get("/api/health").json()["database"] == "mysql"
    runs = client.get("/api/scan/summaries?market=CN").json()
    assert runs[0]["id"] == result["run_id"]
    assert client.get("/api/scan/summaries?market=US").json() == []
    assert client.get(f"/api/scan/{result['run_id']}/results?market=US").status_code == 404
    events = client.get(f"/api/scan/{result['run_id']}/events?market=CN").json()
    assert events["events"][-1]["stage"] == "complete"
    chart = client.get(f"/api/kline/600000.SH?market=CN&source=synthetic&endDate={day}").json()
    assert chart and all(b["date"] <= str(day) for b in chart)
    assert client.get("/api/kline/AAPL.US?market=CN&source=fixture").status_code == 404
    us = client.get("/api/context?market=US").json()
    assert us["currency"] == "USD" and us["security_count"] == 1
    assert client.get("/api/context?market=INVALID").status_code == 422


def test_oral_patch_preserves_unmentioned_facts_and_observation_times(database):
    _, _, original = inputs()
    earlier = now() - timedelta(days=1)
    original.as_of = earlier
    original.positions = [
        Position(symbol=s, currency="CNY", quantity="100", market_value="1000")
        for s in ["600000.SH", "600519.SH"]
    ]
    original.orders = [
        StopOrder(
            symbol="600000.SH",
            order_kind="stop_loss",
            trigger_price="9",
            status="unknown",
            evidence="planned",
        ),
        StopOrder(
            symbol="600000.SH",
            order_kind="take_profit",
            trigger_price="12",
            status="unknown",
            evidence="planned",
        ),
    ]
    saved = save_snapshot(original)
    patch = ManualPatch(
        statement="600000现在剩80股，止盈改13",
        as_of=now(),
        positions=[{"symbol": "600000.SH", "quantity": "80"}],
        orders=[
            {
                "symbol": "600000.SH",
                "order_kind": "take_profit",
                "trigger_price": "13",
                "status": "unknown",
                "evidence": "planned",
            }
        ],
    )
    manual_update("demo", patch)
    row = latest("demo")
    payload = row.payload
    assert payload["previous_snapshot_id"] == saved["snapshot_id"]
    assert payload["statement"] == patch.statement
    positions = {p["symbol"]: p for p in payload["positions"]}
    assert Decimal(positions["600000.SH"]["quantity"]) == 80
    assert positions["600000.SH"]["market_value"] is None
    assert datetime.fromisoformat(positions["600519.SH"]["observed_at"]) == earlier
    assert datetime.fromisoformat(payload["assets_as_of"]) == earlier
    assert len(payload["orders"]) == 2
    assert (
        next(o for o in payload["orders"] if o["order_kind"] == "stop_loss")["trigger_price"] == "9"
    )
    assert (
        next(o for o in payload["orders"] if o["order_kind"] == "take_profit")["trigger_price"]
        == "13"
    )
    with pytest.raises(ValueError, match="broker verification"):
        manual_update(
            "demo",
            ManualPatch(
                statement="invalid",
                as_of=now(),
                orders=[
                    {"symbol": "600000.SH", "evidence": "broker_verified", "status": "unknown"}
                ],
            ),
        )
    assert latest("demo").id == row.id
    with pytest.raises(ValidationError, match="Quantity cannot be null"):
        ManualPatch(
            statement="invalid", as_of=now(), positions=[{"symbol": "600000.SH", "quantity": None}]
        )


def test_console_background_scan_reaches_saved_terminal_event(database):
    import time

    imported = import_csv(Path("examples/bars.csv"))
    client = TestClient(create_app())
    launched = client.post(
        "/api/scan/run",
        json={
            "date": imported["max_date"],
            "market": "CN",
            "source": "synthetic",
            "symbols": ["600000.SH"],
        },
    )
    assert launched.status_code == 200
    run_id = launched.json()["run_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get(f"/api/scan/{run_id}/events?market=CN").json()
        if state["events"] and state["events"][-1]["stage"] == "complete":
            break
        time.sleep(0.05)
    else:
        pytest.fail("Background scan did not persist a terminal event")
    assert state["status"] == "success"
    result = client.get(f"/api/scan/{run_id}/summary?market=CN").json()
    assert result["scanDate"] == imported["max_date"]
    rejected = client.post(
        "/api/scan/run",
        headers={"Origin": "https://untrusted.example"},
        json={"date": imported["max_date"], "market": "CN", "source": "synthetic"},
    )
    assert rejected.status_code == 403
