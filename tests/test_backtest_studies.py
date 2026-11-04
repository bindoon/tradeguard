"""Acceptance for identical evidence and separately funded strategy ledgers."""

import json
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from test_backtesting import config, seed
from test_backtesting import installed as installed
from typer.testing import CliRunner

from tradeguard.backtesting import plugins, service, studies
from tradeguard.cli import app
from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import BacktestArtifact, DailyBar, Run


def study(mode="comparison", weights=("0.5", "0.5"), **overrides):
    cfg = config(**overrides).model_dump(mode="json")
    return studies.StudyConfig.model_validate(
        {
            "name": "同口径验收",
            "mode": mode,
            "cases": [
                {"key": f"case_{i}", "weight": weight, "config": {**cfg, "name": f"方案{i}"}}
                for i, weight in enumerate(weights)
            ],
        }
    )


def test_allocated_ledgers_reserve_cash_fees_lots_and_contributions(database, installed):
    seed()
    execution = {**config().execution.model_dump(), "minimum_commission": "5"}
    result = studies.run(study("allocation", ("0.4", "0.4"), execution=execution))
    report = result["study_report"]
    assert report["reserved_cash"] == "2000.0"
    assert [Decimal(c["report"]["metrics"]["final_equity"]) for c in report["cases"]] == [
        Decimal("4590"),
        Decimal("4590"),
    ]
    combined = report["portfolio"]
    assert Decimal(combined["metrics"]["final_equity"]) == Decimal("11180")
    assert Decimal(combined["metrics"]["fees"]) == 20
    assert [Decimal(c["profit"]) for c in report["attribution"]] == [Decimal(590)] * 2
    assert sum(Decimal(c["return_contribution"]) for c in report["attribution"]) == Decimal("0.118")
    assert sum(p["quantity"] for p in combined["positions"]) == 600
    full = service.run(config(execution=execution))["report"]
    assert Decimal(full["metrics"]["total_return"]) * Decimal("0.8") != Decimal("0.118")
    for i, point in enumerate(combined["curve"]):
        assert Decimal(point["equity"]) == Decimal(report["reserved_cash"]) + sum(
            Decimal(case["report"]["curve"][i]["equity"]) for case in report["cases"]
        )


def test_comparison_independent_instances_one_frozen_input_and_replay(
    database, installed, monkeypatch
):
    seed()
    calls = []
    freeze = studies.data.freeze

    def counted(*args, **kwargs):
        calls.append(1)
        return freeze(*args, **kwargs)

    monkeypatch.setattr(studies.data, "freeze", counted)
    result = studies.run(study(portfolio_strategy="acceptance_rotation"))
    report = result["study_report"]
    assert len(calls) == 1
    assert report["portfolio"] is None
    assert [c["report"]["metrics"]["trade_count"] for c in report["cases"]] == [4, 4]
    assert [Decimal(c["initial_cash"]) for c in report["cases"]] == [Decimal(10000)] * 2
    assert report["correlations"][0]["value"] is None  # Short sample is unknown.
    with session() as db, db.begin():
        assert (
            db.scalar(
                select(func.count())
                .select_from(BacktestArtifact)
                .where(
                    BacktestArtifact.run_id == result["id"], BacktestArtifact.key.like("input:%")
                )
            )
            == 2
        )
        bar = db.scalar(select(DailyBar).where(DailyBar.source == "fixture"))
        bar.high = bar.close = Decimal("99")
    replayed = studies.replay(result["id"])
    assert replayed["study_report"]["result_hash"] == report["result_hash"]
    assert len(calls) == 1
    assert service.history("CN", "fixture", "none")[0]["experiment_type"] == "comparison"
    with pytest.raises(ValueError, match="已被执行"):
        studies.execute(result["id"])
    assert service.get(result["id"])["status"] == "success"


def test_repeating_decimal_contributions_sum_exactly(database, installed):
    seed()
    cfg = study(
        "allocation",
        ("0.3", "0.3", "0.3"),
        initial_cash="12000",
        execution={**config().execution.model_dump(), "minimum_commission": "7"},
    )
    report = studies.run(cfg)["study_report"]
    assert Decimal(report["portfolio"]["metrics"]["final_equity"]) == 13158
    contributions = [Decimal(c["return_contribution"]) for c in report["attribution"]]
    assert (
        sum(contributions)
        == Decimal(report["portfolio"]["metrics"]["total_return"])
        == Decimal("0.0965")
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source": "other"},
        {"adjustment": "forward", "price_model": "adjusted_research"},
        {"symbols": ["600000.SH"]},
        {"start": "2025-01-07"},
        {"initial_cash": "9999"},
        {"execution": {**config().execution.model_dump(), "commission": "0.001"}},
    ],
)
def test_rejects_different_shared_inputs(change):
    payload = study().model_dump(mode="json")
    payload["cases"][1]["config"].update(change)
    with pytest.raises(ValidationError, match="共同设置"):
        studies.StudyConfig.model_validate(payload)


def test_bad_weights_disabled_plugins_failed_case_and_scope(database, installed, monkeypatch):
    seed()
    with pytest.raises(ValidationError, match="100%"):
        study("allocation", ("0.6", "0.5"))
    payload = study().model_dump(mode="json")
    payload["cases"][1]["key"] = "case_0"
    with pytest.raises(ValidationError, match="重复"):
        studies.StudyConfig.model_validate(payload)
    plugins.set_enabled("acceptance_signal", False)
    with pytest.raises(ValueError, match="禁用"):
        studies.create(study())
    plugins.set_enabled("acceptance_signal", True)
    identifier = studies.create(study())
    original = studies.engine.run
    count = 0

    def broken(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("验收：第二套策略失败")
        return original(*args, **kwargs)

    monkeypatch.setattr(studies.engine, "run", broken)
    with pytest.raises(ValueError, match="第二套策略失败"):
        studies.execute(identifier)
    assert service.get(identifier)["status"] == "failed"
    assert service.get(identifier)["study_report"] is None
    with session() as db:
        assert db.get(BacktestArtifact, (identifier, "report")) is None
        assert db.get(Run, identifier).kind == "backtest_study"
    with TestClient(create_app()) as client:
        assert (
            client.get(
                f"/api/backtests/{identifier}?market=US&source=fixture&adjustment=none"
            ).status_code
            == 404
        )


def test_allocated_liquidity_is_not_used_twice(database, installed):
    seed()
    with session() as db, db.begin():
        for bar in db.scalars(select(DailyBar)):
            bar.volume = Decimal("100")
    result = studies.run(study("allocation", ("0.5", "0.5")))
    # Each sleeve gets 50 shares of capacity, below the required 100-share lot.
    assert result["study_report"]["portfolio"]["metrics"]["trade_count"] == 0
    assert all(
        c["config"]["execution"]["prior_volume_fraction"] == "0.5"
        for c in result["study_report"]["cases"]
    )


def test_http_queue_cli_contract_and_archive_integrity(database, installed, tmp_path):
    seed()
    cfg = study()
    path = tmp_path / "study.json"
    path.write_text(cfg.model_dump_json(), encoding="utf-8")
    runner = CliRunner()
    checked = runner.invoke(app, ["backtest", "study-preflight", "--file", str(path)])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["data"]["manifest"]["calendar"][-1] == "2025-01-09"
    with TestClient(create_app()) as client:
        launched = client.post("/api/backtests/studies", json=cfg.model_dump(mode="json"))
        assert launched.status_code == 202
        identifier = launched.json()["id"]
        for _ in range(200):
            response = client.get(
                f"/api/backtests/{identifier}?market=CN&source=fixture&adjustment=none"
            )
            assert response.status_code == 200
            if response.json()["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert response.json()["status"] == "success"
        report = runner.invoke(app, ["backtest", "report", "--run", identifier])
        assert report.exit_code == 0
        assert json.loads(report.output)["data"]["study_report"]["mode"] == "comparison"
    with session() as db, db.begin():
        artifact = db.get(BacktestArtifact, (identifier, "report"))
        artifact.payload = {**artifact.payload, "reserved_cash": "999999"}
    with pytest.raises(ValueError, match="校验失败"):
        service.get(identifier)


def test_long_sample_correlation_and_zero_equity_unknown():
    cfg = study()
    values = [Decimal(10000)]
    for i in range(24):
        values.append(values[-1] * (Decimal("1.01") if i % 2 else Decimal("0.99")))
    cases = [
        {
            "key": c.key,
            "initial_cash": "10000",
            "report": {"curve": [{"equity": str(v)} for v in values]},
        }
        for c in cfg.cases
    ]
    result = studies.summarize(cfg, cases, {"input_hash": "synthetic"})
    assert result["correlations"][0]["value"] == pytest.approx(1)
    assert result["correlations"][0]["observations"] == 24
    cases[0]["report"]["curve"] = [{"equity": "0"}] * 25
    unknown = studies.summarize(cfg, cases, {"input_hash": "synthetic"})
    assert unknown["correlations"][0]["value"] is None
    assert unknown["correlations"][0]["observations"] == 0
