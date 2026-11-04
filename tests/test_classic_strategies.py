"""Expected rules are taken from the learning contract, not implementation shape."""

from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_backtesting import config, seed

from tradeguard.backtesting import plugins, service
from tradeguard.backtesting.classic_portfolios import atr_decimal
from tradeguard.backtesting.education import GUIDES
from tradeguard.backtesting.engine import Context, PositionView
from tradeguard.console import create_app
from tradeguard.screening.strategies.classics import wilder_rsi


def frame(closes):
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=len(closes)).strftime("%Y-%m-%d"),
            "close": list(map(float, closes)),
            "open": list(map(float, closes)),
            "high": [float(n) + 1 for n in closes],
            "low": [float(n) - 1 for n in closes],
            "volume": [100000.0] * len(closes),
        }
    )


def plugin(name, **parameters):
    return plugins.discover()[name].create(parameters)


def hit(signal, data):
    return signal.screen("600000.SH", "Synthetic", data, str(data.iloc[-1]["date"])) is not None


def context(series, **overrides):
    cfg = config(
        symbols=list(series),
        combination=None,
        portfolio_strategy="relative_momentum",
        max_weight="1",
        initial_cash="100000",
        **overrides,
    )
    slices = {
        symbol: {
            "symbol": symbol,
            "bars": [
                {
                    "date": str(row["date"]),
                    **{
                        field: str(row[field])
                        for field in ["open", "high", "low", "close", "volume"]
                    },
                }
                for row in data.to_dict("records")
            ],
        }
        for symbol, data in series.items()
    }
    ctx = Context(cfg, slices, {})
    ctx.current_date = max(str(data.iloc[-1]["date"]) for data in series.values())
    ctx.cash = ctx.total_value = Decimal(100000)
    return ctx


def test_moving_average_requires_a_cross_and_parameters_change_warmup():
    signal = plugin("moving_average_cross", fast=2, slow=3)
    assert signal.min_history == 4
    assert hit(signal, frame([10, 10, 9, 12]))
    assert not hit(signal, frame([10, 11, 12, 13]))
    assert bool(signal.exit_signal(frame([10, 10, 11, 8])).iloc[-1])
    with pytest.raises(ValueError, match="快线"):
        plugin("moving_average_cross", fast=20, slow=10)


def test_donchian_excludes_today_and_equality_is_not_breakout():
    signal = plugin("donchian_breakout", entry=3, exit=2)
    data = frame([10, 10, 10, 12])
    assert hit(signal, data)  # Today's high=13 must not raise the entry threshold.
    data.loc[data.index[-1], "close"] = 11  # Previous highs are exactly 11.
    assert not hit(signal, data)
    assert bool(signal.exit_signal(frame([10, 10, 10, 8])).iloc[-1])


def test_rsi2_trend_filter_extreme_pullback_and_flat_window():
    signal = plugin("rsi2_reversion")
    data = frame([10] * 200 + list(range(100, 111)) + list(range(109, 99, -1)))
    assert hit(signal, data)
    assert not hit(signal, frame(list(range(230, 9, -1))))  # Decline below long MA.
    assert float(wilder_rsi(pd.Series([10.0] * 10), 2).iloc[-1]) == 50
    assert float(wilder_rsi(pd.Series([10.0, 11.0, 12.0]), 2).iloc[-1]) == 100
    assert float(wilder_rsi(pd.Series([12.0, 11.0, 10.0]), 2).iloc[-1]) == 0
    assert bool(signal.exit_signal(frame([100] * 200 + [110])).iloc[-1])


def test_bollinger_requires_return_inside_and_absolute_momentum_is_exact():
    boll = plugin("bollinger_reversion", window=5, deviations=1, trend=None)
    assert hit(boll, frame([100] * 20 + [80, 95]))
    assert not hit(boll, frame([100] * 20 + [80, 80]))
    data = frame([100, 100, 100, 110])
    assert hit(plugin("absolute_momentum", lookback=3, minimum_return="0.05"), data)
    exact = plugin("absolute_momentum", lookback=3, minimum_return="0.1")
    assert not hit(exact, data)  # 10% equals the threshold; float error must not admit it.
    assert bool(exact.exit_signal(data).iloc[-1])


@pytest.mark.parametrize(
    "name,parameters,prices",
    [
        ("moving_average_cross", {"fast": 2, "slow": 3}, [10, 10, 9, 12, 13]),
        ("donchian_breakout", {"entry": 3, "exit": 2}, [10, 10, 10, 12, 13]),
        ("rsi2_reversion", {"trend": 10}, [10] * 20 + [100, 99, 98, 97, 96, 95]),
        (
            "bollinger_reversion",
            {"window": 5, "deviations": 1, "trend": None},
            [100] * 20 + [80, 95],
        ),
        ("absolute_momentum", {"lookback": 3}, [10, 10, 10, 12, 13]),
    ],
)
def test_new_signals_never_change_past_signals_when_future_is_appended(name, parameters, prices):
    signal = plugin(name, **parameters)
    data = frame(prices)
    future = frame(prices + [10000])
    pd.testing.assert_series_equal(signal.entry_signal(data), signal.entry_signal(future).iloc[:-1])


def test_relative_rotation_ranks_known_evidence_and_keeps_unknown_held_positions():
    ctx = context({"600000.SH": frame([10, 10, 12, 13]), "600001.SH": frame([10, 10, 11, 11])})
    rotation = plugin("relative_momentum", lookback=2, skip=1, top_n=1)
    targets = rotation.on_close(ctx)
    assert targets == {"600000.SH": Decimal(1)}
    assert ctx.decisions["600000.SH"]["momentum"] == "0.2"
    ctx = context({"600000.SH": frame([10, 10, 9, 9]), "600001.SH": frame([10, 10, 8, 8])})
    assert rotation.on_close(ctx) == {"600000.SH": Decimal(1)}  # Relative-only can buy a loser.
    ctx = context({"600000.SH": frame([10, 10, 12, 13]), "600001.SH": frame([10, 10, 11, 11])})
    ctx._slices["600001.SH"]["bars"] = ctx._slices["600001.SH"]["bars"][-1:]
    ctx.positions = {"600001.SH": PositionView(1000, Decimal(11), Decimal(11), Decimal(11000))}
    targets = rotation.on_close(ctx)
    assert "600001.SH" not in targets  # Missing history is not a forced liquidation.
    assert targets["600000.SH"] == Decimal("0.89")
    assert ctx.unknown


def test_dual_momentum_defensive_cash_unknown_and_validation():
    ctx = context(
        {
            "600000.SH": frame([10, 10, 9]),
            "600001.SH": frame([10, 10, 8]),
            "600002.SH": frame([10, 10, 10]),
        }
    )
    dual = plugin("dual_momentum", lookback=2, top_n=1, defensive_symbol="600002.SH")
    assert dual.on_close(ctx) == {"600002.SH": Decimal(1)}
    cash = plugin("dual_momentum", lookback=2, top_n=1)
    assert cash.on_close(context({"600000.SH": frame([10, 10, 9])})) == {}
    ctx._slices["600000.SH"]["bars"] = ctx._slices["600000.SH"]["bars"][-1:]
    assert dual.on_close(ctx) == {}  # Unknown is not proof of weak markets.
    cfg = config(
        portfolio_strategy="dual_momentum",
        combination=None,
        strategy_parameters={"defensive_symbol": "600002.SH"},
    )
    with pytest.raises(ValueError, match="防御资产"):
        dual.validate_config(cfg)


def test_turtle_uses_decimal_risk_and_only_confirms_real_quantity_increases():
    turtle = plugin(
        "turtle_daily", entry=2, exit=2, atr_period=2, risk_per_unit="0.01", max_units=2
    )
    ctx = context({"600000.SH": frame([10, 10, 12])}, max_positions=1)
    assert atr_decimal(ctx.history("600000.SH", as_decimal=True), 2) == Decimal("2.5")
    assert turtle.on_close(ctx) == {"600000.SH": Decimal("0.024")}
    assert turtle.states == {}
    assert turtle.on_close(ctx) == {
        "600000.SH": Decimal("0.024")
    }  # Rejected intention is not a filled unit.
    ctx.positions = {"600000.SH": PositionView(100, Decimal(12), Decimal(12), Decimal(1200))}
    turtle.on_close(ctx)
    assert turtle.states["600000.SH"]["units"] == 1
    # Raise only the current close so a second unit may be requested, not yet confirmed.
    bar = ctx._slices["600000.SH"]["bars"][-1]
    bar.update(close="15", high="16", low="11")
    ctx.positions = {"600000.SH": PositionView(100, Decimal(12), Decimal(15), Decimal(1500))}
    assert turtle.on_close(ctx)["600000.SH"] > Decimal("0.015")
    assert turtle.states["600000.SH"]["units"] == 1
    turtle.on_close(ctx)  # No actual added shares.
    assert turtle.states["600000.SH"]["units"] == 1
    ctx.positions = {"600000.SH": PositionView(200, Decimal(13), Decimal(15), Decimal(3000))}
    turtle.on_close(ctx)
    assert turtle.states["600000.SH"]["units"] == 2
    assert turtle.states["600000.SH"]["last_fill"] == Decimal(14)
    bar.update(close="2", high="16", low="1")
    assert turtle.on_close(ctx) == {"600000.SH": Decimal(0)}
    assert "退出" in ctx.decisions["600000.SH"]["summary"]


def test_library_api_guides_parameters_and_native_report_are_frozen(database, monkeypatch):
    catalog = TestClient(create_app()).get("/api/backtests/plugins").json()
    by_name = {item["name"]: item for item in catalog}
    assert len(GUIDES) == 16
    assert set(GUIDES) <= set(by_name)
    for name in GUIDES:
        guide = by_name[name]["education"]
        assert all(
            guide[key]
            for key in [
                "idea",
                "entry",
                "exit",
                "example",
                "pitfalls",
                "variant",
                "sources",
                "suitable_for",
            ]
        )
    assert by_name["relative_momentum"]["uses_signals"] is False
    assert (
        by_name["moving_average_cross"]["parameters_schema"]["properties"]["fast"]["title"]
        == "快线周期"
    )
    seed()
    cfg = config(
        portfolio_strategy="relative_momentum",
        combination=None,
        max_positions=1,
        strategy_parameters={"lookback": 2, "skip": 0, "top_n": 1},
    )
    result = service.run(cfg)
    assert result["manifest"]["warmup"][0]["required"] == 3
    assert result["config"]["combination"] is None
    assert result["report"]["trades"]
    assert result["report"]["orders"][0]["signal_evidence"] == {}
    assert result["report"]["orders"][0]["decision_evidence"]["summary"] == "相对动量排名调仓"
    assert (
        result["plugins"][0]["education"]["entry"]
        == by_name["relative_momentum"]["education"]["entry"]
    )
    original_idea = result["plugins"][0]["education"]["idea"]
    monkeypatch.setitem(
        GUIDES, "relative_momentum", {**GUIDES["relative_momentum"], "idea": "未来修订的说明"}
    )
    assert service.get(result["id"])["plugins"][0]["education"]["idea"] == original_idea
    with pytest.raises(ValueError, match="清空信号组合"):
        plugins.resolve(
            config(
                portfolio_strategy="relative_momentum",
                strategy_parameters={"top_n": 1},
                combination={"signals": [{"name": "donchian_breakout"}]},
            )
        )
