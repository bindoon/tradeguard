import json
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_discipline import inputs
from typer.testing import CliRunner

from tradeguard.cli import app
from tradeguard.db.models import DailyBar
from tradeguard.discipline.service import check, save_rules
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import import_csv, save_bars
from tradeguard.portfolio.service import latest, save_snapshot
from tradeguard.screening.service import scan


def test_migration_and_import_scan_cli(database):
    command.check(Config("alembic.ini"))
    first = import_csv(Path("examples/bars.csv"))
    import_csv(Path("examples/bars.csv"))
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DailyBar)) == first["rows"]
    target = date.fromisoformat(first["max_date"])
    before = scan(target, "synthetic")
    future = BarInput(
        symbol="600000.SH",
        trade_date="2099-01-01",
        source="synthetic",
        adjustment="forward",
        open="100",
        high="100",
        low="100",
        close="100",
        volume="1",
    )
    save_bars([future])
    after = scan(target, "synthetic")
    assert before["input_hash"] == after["input_hash"]
    assert before["candidates"] == after["candidates"]
    assert scan(date(2026, 1, 1), "synthetic")["status"] == "partial"
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["database"] == "connected"
    result = CliRunner().invoke(
        app, ["scan", "run", "--date", str(target), "--source", "synthetic"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["input_hash"] == after["input_hash"]


def test_snapshot_immutability_and_persisted_check(database):
    intent, rules, snapshot = inputs()
    saved = save_snapshot(snapshot)
    assert save_snapshot(snapshot)["reused"]
    with pytest.raises(ValueError, match="different content"):
        save_snapshot(snapshot.model_copy(update={"cash": snapshot.cash - 1}))
    assert latest("demo").id == saved["snapshot_id"]
    profile = save_rules(rules)
    result = check(intent, profile["profile_id"])
    assert result["decision"] == "pass"
    assert result["snapshot_id"] == saved["snapshot_id"]


def test_invalid_csv_is_atomic(database, tmp_path):
    csv = tmp_path / "invalid.csv"
    csv.write_text(Path("examples/bars.csv").read_text().replace("101.00", "1.00", 1))
    with pytest.raises(ValueError):
        import_csv(csv)
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(DailyBar)) == 0


def test_manual_import_rejects_broker_verified_order(database):
    _, _, snapshot = inputs()
    from tradeguard.portfolio.schemas import StopOrder

    snapshot.orders = [
        StopOrder(
            symbol="600000.SH",
            quantity="100",
            trigger_price="9",
            status="active",
            evidence="broker_verified",
        )
    ]
    with pytest.raises(ValueError, match="cannot claim"):
        save_snapshot(snapshot)
    assert latest("demo") is None


def test_cli_portfolio_to_discipline_journey(database, tmp_path):
    intent, rules, snapshot = inputs()
    runner = CliRunner()
    account_file, rules_file, intent_file = [
        tmp_path / name for name in ("snapshot.json", "rules.json", "intent.json")
    ]
    account_file.write_text(snapshot.model_dump_json())
    rules_file.write_text(rules.model_dump_json())
    intent_file.write_text(intent.model_dump_json())
    imported = runner.invoke(app, ["portfolio", "import", "--file", str(account_file)])
    assert imported.exit_code == 0, imported.output
    report = runner.invoke(app, ["portfolio", "report", "--account", "demo"])
    assert report.exit_code == 0, report.output
    profile = runner.invoke(app, ["discipline", "rules-import", "--file", str(rules_file)])
    assert profile.exit_code == 0, profile.output
    profile_id = json.loads(profile.output)["data"]["profile_id"]
    checked = runner.invoke(
        app, ["discipline", "check", "--file", str(intent_file), "--profile", profile_id]
    )
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["data"]["decision"] == "pass"
    intent.stop_evidence = "planned"
    intent_file.write_text(intent.model_dump_json())
    unconfirmed = runner.invoke(
        app, ["discipline", "check", "--file", str(intent_file), "--profile", profile_id]
    )
    assert unconfirmed.exit_code == 3, unconfirmed.output
    assert json.loads(unconfirmed.output)["status"] == "needs_input"


def test_daily_defaults_to_cached_data_without_network(database, monkeypatch):
    from tradeguard.jobs import daily

    imported = import_csv(Path("examples/bars.csv"))

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline daily must not fetch external data")

    monkeypatch.setattr("tradeguard.jobs.sync", forbidden)
    result = daily(date.fromisoformat(imported["max_date"]), source="synthetic")
    assert result["status"] == "success"
    assert result["scan"]["source"] == "synthetic"


def test_daily_cli_passes_explicit_market(monkeypatch):
    import tradeguard.jobs

    received = {}

    def fake_daily(target, symbols, source, refresh, market_code):
        received.update(market=market_code, source=source)
        return {"status": "success"}

    monkeypatch.setattr(tradeguard.jobs, "daily", fake_daily)
    result = CliRunner().invoke(
        app,
        ["pipeline", "daily", "--market", "US", "--source", "longbridge", "--date", "2026-10-16"],
    )
    assert result.exit_code == 0, result.output
    assert received == {"market": "US", "source": "longbridge"}
