"""Independent next-open, multi-asset and fee reference using Backtrader.

No Backtrader source is copied or used by the application runtime. The reference
uses matching simple assumptions; liquidity/settlement/rounding differences are
covered separately rather than claiming every execution model is identical.
"""

from decimal import Decimal

import backtrader as bt
import pandas as pd
import pytest
from test_backtesting import TestSignal, config, slices

from tradeguard.backtesting import engine
from tradeguard.backtesting.plugins import PortfolioStrategy


class Roundtrip(PortfolioStrategy):
    def on_close(self, context):
        self.calls = getattr(self, "calls", 0) + 1
        return {
            symbol: context.config.max_weight if self.calls == 1 else Decimal(0)
            for symbol in context.universe
        }


@pytest.mark.parametrize("charged", [False, True])
def test_matches_backtrader_multi_asset_next_open_and_fee_ledger(charged):
    inputs = slices()
    cfg = config(
        max_weight="0.4",
        execution={
            **config().execution.model_dump(),
            "commission": "0.0003" if charged else "0",
            "minimum_commission": "5" if charged else "0",
            "sell_tax": "0.001" if charged else "0",
        },
    )
    reference = []

    class Costs(bt.CommInfoBase):
        params = (("stocklike", True), ("commtype", bt.CommInfoBase.COMM_PERC))

        def _getcommission(self, size, price, pseudoexec):
            notional = abs(size) * price
            return max(
                notional * float(cfg.execution.commission), float(cfg.execution.minimum_commission)
            ) + (notional * float(cfg.execution.sell_tax) if size < 0 else 0)

    class Strategy(bt.Strategy):
        def next(self):
            if len(self) == 1:
                for feed in self.datas:
                    self.order_target_percent(feed, target=float(cfg.max_weight))
            elif len(self) == 2:
                for feed in self.datas:
                    self.close(feed)

        def notify_order(self, order):
            if order.status == order.Completed:
                reference.append(
                    (
                        order.data._name,
                        bt.num2date(order.executed.dt).date().isoformat(),
                        abs(order.executed.size),
                        order.executed.price,
                        order.executed.comm,
                    )
                )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(cfg.initial_cash))
    cerebro.broker.addcommissioninfo(Costs())
    for symbol, value in inputs.items():
        frame = pd.DataFrame(value["bars"])
        frame.index = pd.to_datetime(frame.pop("date"))
        for field in ("open", "high", "low", "close", "volume"):
            frame[field] = frame[field].astype(float)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=symbol)
    cerebro.addstrategy(Strategy)
    cerebro.run()
    actual = engine.run(
        cfg,
        inputs,
        {"calendar": [b["date"] for b in inputs[cfg.symbols[0]]["bars"]], "warnings": []},
        {TestSignal.name: TestSignal()},
        Roundtrip(),
    )
    assert len(reference) == len(actual["trades"]) == 4
    for expected, trade in zip(reference, actual["trades"], strict=True):
        assert expected[:3] == (trade["symbol"], trade["date"], trade["quantity"])
        assert float(trade["price"]) == pytest.approx(expected[3])
        assert float(trade["fee"]) == pytest.approx(expected[4])
    assert float(actual["metrics"]["final_equity"]) == pytest.approx(cerebro.broker.getvalue())
