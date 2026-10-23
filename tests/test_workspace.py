from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import DailyBar, Notification, Run, ScanResult, WatchItem, now
from tradeguard.discipline.service import save_rules
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import import_csv, save_bars
from tradeguard.workspace.schemas import AlertInput, Scope, WatchInput
from tradeguard.workspace.service import (
    add_alert,
    add_watch,
    inbox,
    mark_read,
    overview,
    refresh,
    search,
    today,
    watches,
)


def bars_today():
    return save_bars(
        [
            BarInput(
                symbol=symbol,
                name=name,
                trade_date=today(),
                source=source,
                adjustment=adj,
                open=price,
                close=price,
                high=price,
                low=price,
                volume="1000",
            )
            for symbol, name, source, adj, price in [
                ("600000.SH", "Synthetic local", "fixture", "forward", "10.00000001"),
                ("600000.SH", "Synthetic local", "other", "forward", "99"),
                ("600000.SH", "Synthetic local", "fixture", "none", "88"),
                ("AAPL.US", "Synthetic US", "fixture", "forward", "20"),
            ]
        ]
    )


def test_watch_persistence_scope_reason_and_invalid_association(database):
    bars_today()
    scope = Scope(market="CN", source="fixture")
    first = add_watch(WatchInput(**scope.model_dump(), symbol="600000.SH", reason="待复核成交量"))
    second = add_watch(WatchInput(**scope.model_dump(), symbol="600000.SH", reason="更新研究依据"))
    assert first["id"] == second["id"]
    row = watches(scope)[0]
    assert row["reason"] == "更新研究依据"
    assert Decimal(row["close"]) == Decimal("10.00000001")
    assert watches(Scope(market="US", source="fixture")) == []
    assert watches(Scope(market="CN", source="other")) == []
    assert row["signal_date"] is None
    with pytest.raises(ValueError, match="该市场"):
        add_watch(WatchInput(**scope.model_dump(), symbol="AAPL.US"))
    with pytest.raises(ValueError, match="关联扫描"):
        add_watch(WatchInput(**scope.model_dump(), symbol="600000.SH", scan_run_id="unknown"))
    assert search(scope, "Synthetic")[0]["symbol"] == "600000.SH"
    assert search(scope, "AAPL") == []
    assert search(scope, "%") == []
    assert overview(scope)["report"] is None


def test_price_alert_decimal_once_read_and_no_old_or_future_evidence(database):
    bars_today()
    scope = Scope(market="CN", source="fixture")
    add_alert(
        AlertInput(
            **scope.model_dump(), symbol="600000.SH", condition="above", target_price="10.00000002"
        )
    )
    triggered = add_alert(
        AlertInput(
            **scope.model_dump(), symbol="600000.SH", condition="above", target_price="10.00000001"
        )
    )
    refresh(scope)
    refresh(scope)
    rows = inbox(scope)
    assert len(rows) == 1
    assert rows[0]["evidence"]["price"] == "10.00000001"
    assert rows[0]["evidence"]["trade_date"] == str(today())
    assert rows[0]["evidence"]["currency"] == "CNY"
    assert mark_read(rows[0]["id"])["read"]
    assert inbox(scope)[0]["read"]
    with session() as db, db.begin():
        old = db.get(DailyBar, ("600000.SH", today(), "fixture", "forward"))
        old.trade_date = today() - timedelta(days=30)
    add_alert(
        AlertInput(**scope.model_dump(), symbol="600000.SH", condition="below", target_price="100")
    )
    refresh(scope)
    assert len(inbox(scope)) == 1
    with pytest.raises(ValueError, match="未来"):
        refresh(scope, today() + timedelta(days=1))
    assert inbox(Scope(market="US", source="fixture")) == []
    assert inbox(Scope(market="CN", source="other")) == []
    with session() as db:
        evidence = db.scalar(select(Notification).where(Notification.kind == "price"))
        assert evidence is not None and triggered["id"]


def test_new_signal_uses_watch_baseline_and_filters_before_limit(database):
    bars_today()
    scope = Scope(market="CN", source="fixture")
    add_watch(WatchInput(**scope.model_dump(), symbol="600000.SH"))
    with session() as db, db.begin():
        watch = db.scalar(select(WatchItem))
        watch.created_at = now() - timedelta(hours=1)
        for index, source in enumerate(["fixture", "other", "other", "other", "other"]):
            run = Run(
                kind="scan",
                market="CN",
                market_date=today(),
                status="success",
                started_at=now() + timedelta(seconds=index),
                details={"source": source, "adjustment": "forward"},
            )
            db.add(run)
            db.flush()
            db.add(
                ScanResult(
                    run_id=run.id,
                    symbol="600000.SH",
                    trade_date=today(),
                    hits=["ma_golden_cross"],
                    close="10",
                    resonance_count=1,
                )
            )
    refresh(scope)
    refresh(scope)
    rows = inbox(scope)
    assert len(rows) == 1 and rows[0]["kind"] == "signal"
    client = TestClient(create_app())
    response = client.get("/api/stocks/600000.SH/signals?market=CN&source=fixture&limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["strategies"] == ["ma_golden_cross"]
    assert (
        client.get(
            "/api/stocks/600000.SH/signals?market=CN&source=fixture&endDate=2020-01-01"
        ).json()
        == []
    )


def test_workspace_http_writes_and_explicit_discipline_profile(database):
    from test_discipline import inputs

    from tradeguard.portfolio.service import save_snapshot

    bars_today()
    intent, rules, snapshot = inputs()
    saved = save_rules(rules)
    save_snapshot(snapshot)
    client = TestClient(create_app())
    payload = {"market": "CN", "source": "fixture", "symbol": "600000.SH", "reason": "Synthetic"}
    assert client.post("/api/watchlist", json=payload).status_code == 200
    assert (
        client.post(
            "/api/watchlist", json=payload, headers={"Origin": "https://foreign.invalid"}
        ).status_code
        == 403
    )
    result = client.post(
        "/api/discipline/check",
        json={"profile_id": saved["profile_id"], "intent": intent.model_dump(mode="json")},
    )
    assert result.status_code == 200
    assert result.json()["rule_profile_id"] == saved["profile_id"]
    assert result.json()["snapshot_id"] is not None
    assert result.json()["decision"] == "pass"
    workspace = client.get("/api/workspace?market=CN&source=fixture").json()
    assert workspace["profiles"][0]["id"] == saved["profile_id"]
    assert workspace["recent_checks"][0]["symbol"] == intent.symbol
    assert client.get("/api/workspace?market=US&source=fixture").json()["recent_checks"] == []
    assert (
        client.get("/api/workspace?market=CN&source=fixture&target=2099-01-01").status_code == 422
    )
    bad = client.post(
        "/api/discipline/check",
        json={
            "profile_id": saved["profile_id"],
            "intent": {**intent.model_dump(mode="json"), "stop_evidence": "broker_verified"},
        },
    )
    assert bad.status_code == 422
    record = client.get("/api/watchlist?market=CN&source=fixture").json()[0]
    assert client.delete("/api/watchlist/" + record["id"]).status_code == 200
    assert client.get("/api/watchlist?market=CN&source=fixture").json() == []


def test_workspace_daily_report_does_not_mix_adjustments(database):
    imported = import_csv(Path("examples/bars.csv"))
    from tradeguard.screening.service import scan

    target = date.fromisoformat(imported["max_date"])
    scan(target, "synthetic", adjustment="forward")
    assert overview(Scope(market="CN", source="synthetic"))["report"]["adjustment"] == "forward"
    assert overview(Scope(market="CN", source="synthetic", adjustment="none"))["report"] is None


def test_local_port_is_same_origin_but_foreign_origins_are_rejected(database):
    bars_today()
    client = TestClient(create_app(), base_url="http://127.0.0.1:8190")
    payload = {"market": "CN", "source": "fixture", "symbol": "600000.SH"}
    assert (
        client.post(
            "/api/watchlist", json=payload, headers={"Origin": "http://127.0.0.1:8190"}
        ).status_code
        == 200
    )
    for origin in [
        "https://foreign.invalid",
        "http://127.0.0.1:9001",
        "http://127.0.0.1:8190.attacker.invalid",
    ]:
        assert (
            client.post("/api/watchlist", json=payload, headers={"Origin": origin}).status_code
            == 403
        )


def test_position_review_keeps_missing_evidence_unknown_and_uses_recorded_exit(database):
    from test_discipline import inputs

    from tradeguard.portfolio.schemas import Position, StopOrder
    from tradeguard.portfolio.service import save_snapshot
    from tradeguard.workspace.service import position_reviews

    bars_today()
    _, _, snapshot = inputs()
    snapshot.broker = "fixture_broker"
    snapshot.positions = [Position(symbol="600000.SH", quantity="100", currency="CNY")]
    snapshot.orders = [
        StopOrder(
            symbol="600000.SH",
            order_kind="take_profit",
            trigger_price="10",
            quantity="100",
            status="unknown",
            evidence="planned",
        )
    ]
    save_snapshot(snapshot)
    scope = Scope(market="CN", source="fixture")
    review = position_reviews(scope)[0]
    assert review["decision"] == "needs_input"
    assert any("planned" in reason and "止盈" in reason for reason in review["reasons"])
    assert any("券商保护单证据" in reason for reason in review["reasons"])
    assert position_reviews(Scope(market="US", source="fixture")) == []
    snapshot.external_id = "verified"
    snapshot.as_of = now()
    snapshot.orders.append(
        StopOrder(
            symbol="600000.SH",
            order_kind="stop_loss",
            trigger_price="9",
            quantity="100",
            status="active",
            evidence="broker_verified",
            observed_at=now(),
        )
    )
    snapshot.broker = "fixture_broker"
    snapshot.record_origin = "broker_api"
    save_snapshot(snapshot, broker_verified=True)
    assert position_reviews(scope)[0]["decision"] == "review_exit"
    assert position_reviews(Scope(market="CN", source="missing"))[0]["decision"] == "needs_input"


def test_workspace_cli_and_migration_round_trip(database, tmp_path):
    import json

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from typer.testing import CliRunner

    from tradeguard.cli import app

    bars_today()
    runner = CliRunner()
    watch_file = tmp_path / "watch.json"
    watch_file.write_text(
        json.dumps(
            {
                "market": "CN",
                "source": "fixture",
                "symbol": "600000.SH",
                "reason": "Synthetic CLI evidence",
            }
        )
    )
    saved = runner.invoke(app, ["workspace", "watch", "--file", str(watch_file)])
    assert saved.exit_code == 0, saved.output
    assert json.loads(saved.output)["data"]["symbol"] == "600000.SH"
    report = runner.invoke(app, ["workspace", "report", "--market", "CN", "--source", "fixture"])
    assert report.exit_code == 0, report.output
    assert json.loads(report.output)["data"]["watchlist"][0]["reason"] == "Synthetic CLI evidence"
    refreshed = runner.invoke(
        app, ["workspace", "refresh", "--market", "CN", "--source", "fixture"]
    )
    assert refreshed.exit_code == 0, refreshed.output
    assert json.loads(refreshed.output)["data"]["mode"] == "cached_observations"
    public = runner.invoke(
        app,
        [
            "public",
            "export",
            "--market",
            "CN",
            "--source",
            "fixture",
            "--date",
            str(today()),
            "--symbol",
            "600000.SH",
            "--output",
            str(tmp_path / "public-cli"),
        ],
    )
    assert public.exit_code == 0, public.output
    assert json.loads(public.output)["data"]["private_data"] is False
    command.downgrade(Config("alembic.ini"), "c4e8b1a07f23")
    assert "watch_item" not in inspect(database).get_table_names()
    with session() as db:
        assert db.get(DailyBar, ("600000.SH", today(), "fixture", "forward")) is not None
    command.upgrade(Config("alembic.ini"), "head")
    assert "watch_item" in inspect(database).get_table_names()
    assert watches(Scope(market="CN", source="fixture")) == []


def test_candidate_to_watch_keeps_saved_batch_and_reason(database):
    from tradeguard.db.models import ScanSummary

    bars_today()
    scope = Scope(market="CN", source="fixture")
    with session() as db, db.begin():
        run = Run(
            kind="scan",
            market="CN",
            market_date=today(),
            status="partial",
            details={"source": "fixture", "adjustment": "forward"},
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.add(
            ScanResult(
                run_id=run_id,
                symbol="600000.SH",
                trade_date=today(),
                hits=["ma_golden_cross", "macd_golden_cross"],
                close="10.00000001",
                resonance_count=2,
                metadata_snapshot={
                    "name": "Synthetic candidate",
                    "strategy_details": [
                        {"title": "Synthetic evidence", "reason": "saved observation"}
                    ],
                },
            )
        )
        db.add(
            ScanSummary(
                run_id=run_id,
                market="CN",
                trade_date=today(),
                source="fixture",
                adjustment="forward",
                status="partial",
                universe_count=1,
                scanned_count=1,
                hit_count=1,
                resonance_count=1,
                market_regime="unknown",
            )
        )
    data = overview(scope)
    assert data["report"]["status"] == "partial"
    pick = data["report"]["top_resonance"][0]
    assert pick["symbol"] == "600000.SH"
    assert pick["resonance_count"] == 2
    assert "saved observation" in pick["reasons"][0]
    saved = add_watch(
        WatchInput(
            **scope.model_dump(),
            symbol=pick["symbol"],
            reason="Review saved evidence",
            scan_run_id=run_id,
        )
    )
    watch = watches(scope)[0]
    assert watch["id"] == saved["id"]
    assert watch["scan_run_id"] == run_id
    assert watch["signal_date"] == str(today())
    assert watch["reason"] == "Review saved evidence"
    with pytest.raises(ValueError, match="关联扫描"):
        add_watch(WatchInput(market="US", source="fixture", symbol="AAPL.US", scan_run_id=run_id))


def test_screener_uses_selected_adjustment_and_no_future_date(database):
    from tradeguard.screening.service import scan

    bars_today()
    with session() as db, db.begin():
        raw = db.get(DailyBar, ("600000.SH", today(), "fixture", "none"))
        raw.trade_date = today() - timedelta(days=1)
    client = TestClient(create_app())
    raw_result = client.get(
        "/api/stock-pool/filter?market=CN&source=fixture&adjustment=none"
    ).json()
    assert raw_result["date"] == str(today() - timedelta(days=1))
    forward = client.get(
        "/api/stock-pool/filter?market=CN&source=fixture&adjustment=forward"
    ).json()
    assert forward["date"] == str(today())
    assert (
        client.get(
            "/api/stock-pool/filter?market=CN&source=fixture&target_date=2099-01-01"
        ).status_code
        == 422
    )
    with pytest.raises(ValueError, match="future"):
        scan(today() + timedelta(days=1), "fixture")
