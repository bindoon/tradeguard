from decimal import Decimal
from types import SimpleNamespace as Obj

import pytest
from test_discipline import inputs

from tradeguard.portfolio.longbridge import collect
from tradeguard.portfolio.service import latest, save_snapshot


class Trade:
    def stock_positions(self):
        return Obj(
            channels=[
                Obj(
                    positions=[
                        Obj(
                            symbol="00700.HK",
                            quantity=Decimal("100"),
                            currency="HKD",
                            cost_price=Decimal("200"),
                        )
                    ]
                )
            ]
        )

    def fund_positions(self):
        return Obj(channels=[])

    def account_balance(self, currency):
        return [
            Obj(
                currency="HKD",
                net_assets=Decimal("100000"),
                init_margin=Decimal("0"),
                cash_infos=[Obj(currency="HKD", available_cash=Decimal("70000"))],
            )
        ]

    def today_orders(self):
        return [
            Obj(
                order_id="1",
                symbol="00700.HK",
                side="OrderSide.Sell",
                order_type="OrderType.LIT",
                status="OrderStatus.New",
                quantity=Decimal("100"),
                executed_quantity=Decimal("0"),
                trigger_price=Decimal("190"),
            )
        ]

    def history_orders(self, *, start_at, end_at):
        return self.today_orders()


class Quotes:
    def quote(self, symbols):
        return [Obj(symbol="700.HK", last_done=Decimal("300"))]


def test_read_only_broker_normalizes_currency_and_deduplicates_orders():
    snapshot = collect(Trade(), Quotes(), "test", "HKD")
    assert snapshot.positions[0].market_value == Decimal("30000")
    assert snapshot.positions[0].currency == "HKD"
    assert len(snapshot.orders) == 1
    assert snapshot.orders[0].evidence == "broker_verified"
    assert snapshot.monthly_drawdown is None


def test_failed_broker_read_cannot_replace_current_snapshot(database):
    _, _, snapshot = inputs()
    original = save_snapshot(snapshot)

    class FailedOrders(Trade):
        def history_orders(self, *, start_at, end_at):
            raise RuntimeError("provider disconnected")

    with pytest.raises(RuntimeError, match="provider disconnected"):
        collected = collect(FailedOrders(), Quotes(), "demo", "HKD")
        save_snapshot(collected, broker_verified=True)
    assert latest("demo").id == original["snapshot_id"]


def test_completed_parent_does_not_hide_active_attached_exits():
    class AttachedTrade(Trade):
        def today_orders(self):
            parent = super().today_orders()[0]
            parent.side = "OrderSide.Buy"
            parent.status = "OrderStatus.Filled"
            parent.executed_quantity = parent.quantity
            parent.attached_orders = [
                Obj(
                    order_id=str(i),
                    quantity=Decimal("100"),
                    executed_qty=Decimal("0"),
                    attached_type_display=kind,
                    trigger_price=Decimal(price),
                    submit_price=Decimal("0"),
                    withdrawn=False,
                    trigger_status="TriggerStatus.Active",
                )
                for i, kind, price in [
                    ("2", "AttachedOrderType.StopLoss", "190"),
                    ("3", "AttachedOrderType.ProfitTaker", "330"),
                ]
            ]
            return [parent]

    result = collect(AttachedTrade(), Quotes(), "fixture", "HKD")
    assert [(o.order_kind, o.status, o.side) for o in result.orders] == [
        ("stop_loss", "active", "sell"),
        ("take_profit", "active", "sell"),
    ]
    assert len(result.orders) == 2
    standalone = collect(Trade(), Quotes(), "fixture", "HKD")
    assert standalone.orders[0].order_kind == "conditional"


def test_funds_are_valued_by_units_and_do_not_leak_into_stock_scope():
    from tradeguard.db.models import now

    observed = now()

    class Funds(Trade):
        def fund_positions(self):
            return Obj(
                channels=[
                    Obj(
                        positions=[
                            Obj(
                                symbol="HK0000000001",
                                symbol_name="Fixture Fund",
                                currency="USD",
                                holding_units=Decimal("5"),
                                current_net_asset_value=Decimal("102"),
                                cost_net_asset_value=Decimal("100"),
                                net_asset_value_day=observed,
                            )
                        ]
                    )
                ]
            )

    combined = collect(Funds(), Quotes(), "fixture", "HKD")
    assert len(combined.positions) == 2
    fund = next(p for p in combined.positions if p.instrument_kind == "other")
    assert fund.market_value == Decimal("510")
    assert fund.observed_at == observed
    stock = collect(Funds(), Quotes(), "fixture", "HKD", "stock")
    assert len(stock.positions) == 1 and stock.net_assets is None and stock.cash is None
    fund_only = collect(Funds(), Quotes(), "fixture", "HKD", "other")
    assert len(fund_only.positions) == 1 and fund_only.orders == []
    assert fund_only.positions[0].symbol == "HK0000000001"
