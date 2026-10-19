from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradeguard.db.models import now
from tradeguard.discipline.schemas import Intent, Rules
from tradeguard.discipline.service import evaluate
from tradeguard.portfolio.schemas import SnapshotInput


def inputs():
    rules = Rules(
        name="test",
        single_stock_limit="0.25",
        max_trade_loss="0.02",
        monthly_drawdown_limit="0.15",
        snapshot_max_age_minutes=60,
        allow_manual_stop_confirmation=True,
    )
    snapshot = SnapshotInput(
        account_id="demo",
        broker="manual",
        label="demo",
        external_id="1",
        as_of=now(),
        base_currency="CNY",
        net_assets="100000",
        cash="100000",
        margin_used=False,
        monthly_drawdown="0",
        positions=[],
        orders=[],
    )
    intent = Intent(
        account_id="demo",
        symbol="600000.SH",
        currency="CNY",
        action="buy",
        style="trend",
        quantity="100",
        price="10",
        stop_price="9",
        stop_evidence="manually_confirmed",
        thesis="synthetic test",
    )
    return intent, rules, snapshot


def test_missing_or_stale_snapshot_never_passes():
    intent, rules, snapshot = inputs()
    assert evaluate(intent, rules, None, now())["decision"] == "needs_input"
    old = snapshot.model_copy(update={"as_of": now() - timedelta(hours=2)})
    assert evaluate(intent, rules, old, now())["decision"] == "needs_input"


def test_trade_after_exposure_and_loss_limits():
    intent, rules, snapshot = inputs()
    assert evaluate(intent, rules, snapshot, now())["decision"] == "pass"
    too_big = intent.model_copy(update={"quantity": Decimal("3000")})
    result = evaluate(too_big, rules, snapshot, now())
    assert set(result["blocked"]) == {"single_stock_limit", "max_trade_loss"}


def test_drawdown_threshold_and_planned_stop_do_not_pass():
    intent, rules, snapshot = inputs()
    planned = intent.model_copy(update={"stop_evidence": "planned"})
    assert evaluate(planned, rules, snapshot, now())["decision"] == "needs_input"
    snapshot.monthly_drawdown = Decimal("-0.15")
    assert "monthly_drawdown_circuit_breaker" in evaluate(intent, rules, snapshot, now())["blocked"]


def test_currency_validation_and_missing_fx():
    intent, rules, snapshot = inputs()
    with pytest.raises(ValidationError):
        Intent.model_validate({**intent.model_dump(), "symbol": "00700.HK"})
    hk = Intent.model_validate({**intent.model_dump(), "symbol": "700.HK", "currency": "HKD"})
    result = evaluate(hk, rules, snapshot, now())
    assert result["decision"] == "needs_input"
    assert "fx:HKD/CNY" in result["missing"]


def test_trend_add_checks_existing_position_and_active_stop():
    intent, rules, snapshot = inputs()
    snapshot = SnapshotInput.model_validate(
        {
            **snapshot.model_dump(),
            "positions": [
                {
                    "symbol": "600000.SH",
                    "currency": "CNY",
                    "quantity": "1000",
                    "market_value": "9000",
                    "average_cost": "11",
                }
            ],
            "orders": [
                {
                    "symbol": "600000.SH",
                    "quantity": "1000",
                    "trigger_price": "8",
                    "status": "active",
                    "evidence": "planned",
                }
            ],
        }
    )
    intent = intent.model_copy(update={"action": "add"})
    result = evaluate(intent, rules, snapshot, now())
    assert "trend_averaging_down" in result["blocked"]
    assert "verified_stop_coverage:600000.SH" in result["missing"]
