import pandas as pd

from tradeguard.screening.strategies.bollinger_breakout import STRATEGY as BOLLINGER
from tradeguard.screening.strategies.box_breakout import STRATEGY as BOX
from tradeguard.screening.strategies.ma_golden_cross import STRATEGY as MA
from tradeguard.screening.strategies.macd_golden_cross import STRATEGY as MACD
from tradeguard.screening.strategies.rsi_rebound import STRATEGY as RSI


def frame(rows: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="B").strftime("%Y-%m-%d"),
            "open": [10.0] * rows,
            "high": [10.5] * rows,
            "low": [9.5] * rows,
            "close": [10.0] * rows,
            "volume": [1_000.0] * rows,
        }
    )


def test_ma_golden_cross_requires_cross_two_days_ago_and_alignment():
    data = frame()
    data["ma5"] = 9.0
    data["ma10"] = 10.0
    data["ma20"] = 11.0
    data["ma60"] = 12.0
    data.loc[data.index[-4], ["ma5", "ma10"]] = [10.0, 10.0]
    data.loc[data.index[-3], ["ma5", "ma10"]] = [11.0, 10.0]
    data.loc[data.index[-1], ["ma5", "ma10", "ma20", "ma60"]] = [14.0, 13.0, 12.0, 11.0]
    assert MA.screen("600000.SH", "测试", data, "2024-04-22") is not None
    missed = data.copy()
    missed.loc[missed.index[-3], ["ma5", "ma10"]] = [9.0, 10.0]
    assert MA.screen("600000.SH", "测试", missed, "2024-04-22") is None


def test_macd_golden_cross_needs_zero_axis_and_ma20():
    data = frame(40)
    data["ma20"] = 9.0
    data["macd"] = -0.1
    data["macd_signal"] = 0.1
    data["macd_hist"] = -0.2
    data.loc[data.index[-1], ["macd", "macd_signal", "macd_hist", "close"]] = [0.4, 0.1, 0.3, 11]
    assert MACD.screen("600000.SH", "测试", data, "2024-02-23") is not None
    below = data.copy()
    below.loc[below.index[-1], "macd"] = -0.2
    assert MACD.screen("600000.SH", "测试", below, "2024-02-23") is None


def test_rsi_rebound_needs_cross_volume_and_bullish_close():
    data = frame(30)
    data["rsi"] = 20.0
    data["volume_ma20"] = 500.0
    data.loc[data.index[-1], ["rsi", "open", "close", "volume"]] = [35.0, 10.0, 10.4, 2_000.0]
    assert RSI.screen("600000.SH", "测试", data, "2024-02-09") is not None
    quiet = data.copy()
    quiet.loc[quiet.index[-1], "volume"] = 100.0
    assert RSI.screen("600000.SH", "测试", quiet, "2024-02-09") is None


def test_bollinger_does_not_repeat_a_breakout():
    data = frame(30)
    data["bb_upper"] = 10.5
    data["bb_middle"] = 10.0
    data["bb_lower"] = 9.5
    data["volume_ma20"] = 500.0
    data.loc[data.index[-2], ["close", "bb_upper"]] = [10.4, 10.5]
    data.loc[data.index[-1], ["close", "high", "volume", "bb_upper"]] = [11.0, 11.2, 2_000.0, 10.5]
    assert BOLLINGER.screen("600000.SH", "测试", data, "2024-02-09") is not None
    continued = data.copy()
    continued.loc[continued.index[-2], "close"] = 11.0
    assert BOLLINGER.screen("600000.SH", "测试", continued, "2024-02-09") is None


def test_box_breakout_needs_tight_range_and_volume_multiple():
    data = frame(50)
    data["box_top"] = 10.5
    data["box_bottom"] = 10.0
    data["box_mid"] = 10.25
    data["box_range_pct"] = 0.05
    data["volume_ma20"] = 1_000.0
    data.loc[data.index[-1], ["close", "high", "volume"]] = [11.0, 11.2, 2_000.0]
    assert BOX.screen("600000.SH", "测试", data, "2024-03-08") is not None
    wide = data.copy()
    wide["box_range_pct"] = 0.2
    assert BOX.screen("600000.SH", "测试", wide, "2024-03-08") is None
    thin = data.copy()
    thin.loc[thin.index[-1], "volume"] = 1_200.0
    assert BOX.screen("600000.SH", "测试", thin, "2024-03-08") is None
