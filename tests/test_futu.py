from decimal import Decimal

import pytest

from tradeguard.portfolio.futu import normalize_snapshot


def test_futu_partial_fill_stop_covers_only_remaining_quantity():
    balance = {"cash": 10000, "frozen_cash": 1000, "debt_cash": 0, "total_assets": 40000}
    position = {
        "code": "HK.00700",
        "qty": 100,
        "market_val": 30000,
        "cost_price": 200,
        "cost_price_valid": True,
        "currency": "HKD",
    }
    order = {
        "order_status": "FILLED_PART",
        "trd_side": "SELL",
        "order_type": "STOP",
        "qty": 100,
        "dealt_qty": 20,
        "aux_price": 190,
        "code": "HK.00700",
    }
    snapshot = normalize_snapshot("demo-futu", "HKD", balance, [position], [order])
    assert snapshot.cash == Decimal(9000)
    assert snapshot.orders[0].quantity == Decimal(80)
    assert snapshot.orders[0].symbol == "00700.HK"
    assert snapshot.orders[0].evidence == "broker_verified"


def test_futu_missing_numeric_fields_are_not_treated_as_zero():
    with pytest.raises(ValueError):
        normalize_snapshot("demo", "HKD", {"cash": "N/A"}, [], [])


def test_futu_retains_take_profit_trailing_and_buy_orders():
    balance = {"cash": 10000, "frozen_cash": 0, "debt_cash": 0, "total_assets": 10000}
    orders = [
        {
            "code": "US.AAPL",
            "order_status": "SUBMITTED",
            "trd_side": side,
            "order_type": kind,
            "qty": 10,
            "dealt_qty": 2,
            "aux_price": price,
            "price": price,
            "order_id": kind,
            "trail_type": "PERCENTAGE",
            "trail_value": 5,
        }
        for kind, side, price in [
            ("STOP_LIMIT", "SELL", 90),
            ("LIMIT_IF_TOUCHED", "SELL", 120),
            ("TRAILING_STOP", "SELL", 0),
            ("NORMAL", "BUY", 100),
        ]
    ]
    result = normalize_snapshot("fixture", "USD", balance, [], orders)
    assert [o.order_kind for o in result.orders] == [
        "stop_loss",
        "take_profit",
        "trailing",
        "limit",
    ]
    assert all(o.quantity == 8 for o in result.orders)
    assert result.orders[2].trailing_percent == 5
    assert result.orders[2].trigger_price is None
    assert result.pending_buy_orders
