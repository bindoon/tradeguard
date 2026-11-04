from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from tradeguard.backtesting.plugins import discover
from tradeguard.backtesting.schemas import Combination
from tradeguard.backtesting.strategy import SignalPortfolio
from tradeguard.db import session
from tradeguard.db.models import Run, ScanResult, ScanSummary, Security
from tradeguard.report import daily_report
from tradeguard.screening.resonance import (
    family_evidence,
    independent_votes,
    ordered_hits,
    rank_key,
)
from tradeguard.screening.service import DEFAULT_STRATEGIES
from tradeguard.screening.strategies.box_breakout import STRATEGY as CLOSE_BOX
from tradeguard.screening.strategies.box_high_breakout import STRATEGY as HIGH_BOX
from tradeguard.screening.strategies.registry import STRATEGY_REGISTRY


def frame(rows=50, *, close=10.0, high=10.2, low=9.8, open_=10.0, volume=1000.0):
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-02", periods=rows).strftime("%Y-%m-%d"),
            "open": [open_] * rows,
            "high": [high] * rows,
            "low": [low] * rows,
            "close": [close] * rows,
            "volume": [volume] * rows,
        }
    )


def screen(strategy, data):
    return strategy.screen("600089.SH", "特变电工", data, str(data.iloc[-1]["date"]))


def test_registry_keeps_both_box_strategies_and_default_scan_uses_them():
    assert STRATEGY_REGISTRY["box_breakout"] is CLOSE_BOX
    assert HIGH_BOX.name == "box_high_breakout"
    assert HIGH_BOX.title == "箱体高点突破确认"
    assert HIGH_BOX.english_name == "Box High Breakout (close-confirmed)"
    assert "最高价" in HIGH_BOX.description and "1%" in HIGH_BOX.description
    assert DEFAULT_STRATEGIES.index("box_high_breakout") == (
        DEFAULT_STRATEGIES.index("box_breakout") + 1
    )
    schema = HIGH_BOX.parameters_model.model_json_schema()["properties"]
    assert schema["box_period"]["default"] == 20
    assert schema["max_box_range_pct"]["default"] == 0.15
    assert schema["min_breakout_pct"]["default"] == 0.01
    assert schema["vol_mult"]["default"] == 1.5


def test_close_above_max_close_but_below_max_high_fires_only_the_old_strategy():
    data = frame(close=17.5, high=17.6, low=17.3, open_=17.45)
    wick = data.index[-5]
    peak = data.index[-10]
    data.loc[peak, ["open", "high", "low", "close"]] = [17.7, 17.96, 17.5, 17.94]
    data.loc[wick, ["open", "high", "low", "close"]] = [17.7, 18.31, 17.6, 17.83]
    data.loc[data.index[-2], ["open", "high", "low", "close"]] = [17.55, 17.7, 17.4, 17.6]
    data.loc[data.index[-1], ["open", "high", "low", "close", "volume"]] = [
        17.8,
        18.05,
        17.7,
        18.0,
        2000.0,
    ]
    old = screen(CLOSE_BOX, data)
    assert old is not None
    assert old["metadata"]["box_top"] == pytest.approx(17.94)
    assert screen(HIGH_BOX, data) is None


def test_genuine_high_breakout_records_the_high_date_and_confirmation():
    data = frame()
    data.loc[data.index[-2], ["open", "high", "low", "close"]] = [10.0, 10.2, 9.8, 10.2]
    data.loc[data.index[-1], ["open", "high", "low", "close", "volume"]] = [
        10.3,
        10.6,
        10.2,
        10.5,
        3000.0,
    ]
    result = screen(HIGH_BOX, data)
    assert result is not None
    meta = result["metadata"]
    assert meta["box_top"] == pytest.approx(10.2)
    assert meta["box_bottom"] == pytest.approx(9.8)
    assert meta["box_mid"] == pytest.approx(10.0)
    assert meta["box_period"] == 20
    assert meta["box_range_pct"] == pytest.approx(0.0408)
    assert meta["breakout_pct"] == pytest.approx(0.029412)
    assert meta["volume"] == pytest.approx(3000)
    assert meta["volume_ratio"] == pytest.approx(2.73)
    assert meta["box_top_date"] == data.iloc[-2]["date"]
    assert set(meta) >= {
        "box_top",
        "box_bottom",
        "box_mid",
        "box_period",
        "box_range_pct",
        "breakout_pct",
        "volume",
        "volume_ma20",
        "volume_ratio",
        "box_top_date",
    }


def test_min_breakout_pct_is_inclusive_and_configurable():
    data = frame(close=10.0, high=10.0, low=9.5, open_=10.0)
    data.loc[data.index[-1], ["open", "high", "low", "volume"]] = [10.0, 10.2, 9.9, 3000.0]
    data.loc[data.index[-1], "close"] = 10.10
    assert screen(HIGH_BOX, data) is not None
    data.loc[data.index[-1], "close"] = 10.09
    assert screen(HIGH_BOX, data) is None
    wider = discover()["box_high_breakout"].create({"min_breakout_pct": 0})
    assert screen(wider, data) is not None


def test_volume_threshold_uses_greater_or_equal():
    data = frame()
    data.loc[data.index[-1], ["open", "high", "low", "close", "volume"]] = [
        10.3,
        10.6,
        10.2,
        10.5,
        1500.0,
    ]
    assert screen(HIGH_BOX, data) is None
    data.loc[data.index[-1], "volume"] = 2000.0
    assert screen(HIGH_BOX, data) is not None
    equal_volume = discover()["box_high_breakout"].create({"vol_mult": 1})
    quiet = frame()
    quiet.loc[quiet.index[-1], ["open", "high", "low", "close"]] = [10.3, 10.6, 10.2, 10.5]
    assert screen(equal_volume, quiet) is not None


def test_first_breakout_does_not_repeat_after_the_previous_close_cleared_its_box():
    data = frame()
    data.loc[data.index[-2], ["open", "high", "low", "close"]] = [10.2, 11.2, 10.2, 11.0]
    data.loc[data.index[-1], ["open", "high", "low", "close", "volume"]] = [
        11.1,
        11.6,
        11.0,
        11.4,
        3000.0,
    ]
    assert screen(HIGH_BOX, data) is None


def test_range_filter_matches_the_close_box_strict_upper_bound():
    wide = frame(close=10.5, high=11.5, low=10.0, open_=10.5)
    wide.loc[wide.index[-1], ["open", "high", "low", "close", "volume"]] = [
        11.6,
        12.0,
        11.4,
        11.8,
        5000.0,
    ]
    assert screen(HIGH_BOX, wide) is None
    tight = frame(close=10.5, high=11.49, low=10.0, open_=10.5)
    tight.loc[tight.index[-1], ["open", "high", "low", "close", "volume"]] = [
        11.6,
        12.0,
        11.4,
        11.8,
        5000.0,
    ]
    assert screen(HIGH_BOX, tight) is not None
    blocked = discover()["box_high_breakout"].create({"max_box_range_pct": 0.01})
    assert screen(blocked, tight) is None


def test_box_family_counts_once_and_ranking_prefers_the_high_breakout():
    assert independent_votes(["box_breakout", "box_high_breakout"]) == 1
    assert independent_votes(["box_breakout", "box_high_breakout", "ma_golden_cross"]) == 2
    assert ordered_hits(["ma_golden_cross", "box_breakout", "box_high_breakout"]) == [
        "ma_golden_cross",
        "box_high_breakout",
        "box_breakout",
    ]
    assert family_evidence(
        [("box_breakout", True), ("box_high_breakout", False), ("ma_golden_cross", None)]
    ) == [True, None]
    assert rank_key(2, ["box_high_breakout", "ma_golden_cross"], "600001.SH") < rank_key(
        2, ["box_breakout", "ma_golden_cross"], "600000.SH"
    )
    with pytest.raises(ValueError, match="家族"):
        Combination.model_validate(
            {
                "mode": "at_least",
                "minimum": 2,
                "signals": [{"name": "box_breakout"}, {"name": "box_high_breakout"}],
            }
        )


def _context(signals, *, mode="at_least", minimum=2, names=None, positions=None, rebalance=True):
    names = names or ["box_breakout", "box_high_breakout", "ma_golden_cross"]
    return SimpleNamespace(
        universe=list(signals),
        positions=positions or {},
        config=SimpleNamespace(
            combination=SimpleNamespace(
                signals=[SimpleNamespace(name=name, lookback=1) for name in names],
                mode=mode,
                minimum=minimum,
            ),
            rank_by="hits",
            max_weight=Decimal("1"),
            invested_fraction=Decimal("1"),
            max_positions=2,
            rebalance=rebalance,
        ),
        signal=lambda name, symbol, lookback: signals[symbol].get(name, False),
        history=lambda symbol, count=None: pd.DataFrame({"close": [10] * 21}),
        note_unknown=lambda symbol: None,
    )


def test_portfolio_votes_collapse_the_box_family_and_prefer_the_confirmed_high():
    portfolio = SignalPortfolio()
    duplicated = _context(
        {
            "600000.SH": {
                "box_breakout": True,
                "box_high_breakout": True,
                "ma_golden_cross": False,
            },
            "600001.SH": {
                "box_breakout": True,
                "box_high_breakout": False,
                "ma_golden_cross": True,
            },
        }
    )
    assert list(portfolio.on_close(duplicated)) == ["600001.SH"]
    preferred = _context(
        {
            "600000.SH": {"box_breakout": True, "box_high_breakout": False},
            "600001.SH": {"box_breakout": False, "box_high_breakout": True},
        },
        mode="any",
        minimum=1,
        names=["box_breakout", "box_high_breakout"],
    )
    preferred.config.max_positions = 1
    assert list(portfolio.on_close(preferred)) == ["600001.SH"]
    held = _context(
        {"600001.SH": {"box_high_breakout": True}},
        mode="any",
        minimum=1,
        names=["box_high_breakout"],
        positions={"600000.SH": object()},
        rebalance=False,
    )
    assert portfolio.on_close(held) == {"600001.SH": Decimal("0.5")}


def test_daily_report_breaks_resonance_ties_toward_box_high_breakout(database):
    target = date(2026, 6, 1)
    with session() as db, db.begin():
        run = Run(
            kind="scan",
            market="CN",
            market_date=target,
            status="success",
            details={"source": "fixture", "adjustment": "forward"},
        )
        db.add(run)
        db.flush()
        rows = (
            ("600000.SH", ["box_breakout", "ma_golden_cross"]),
            ("600001.SH", ["box_high_breakout", "ma_golden_cross"]),
        )
        db.add_all(
            Security(symbol=symbol, name=symbol, market="CN", currency="CNY")
            for symbol, _hits in rows
        )
        db.flush()
        db.add_all(
            ScanResult(
                run_id=run.id,
                symbol=symbol,
                trade_date=target,
                hits=hits,
                close=Decimal("10"),
                resonance_count=2,
            )
            for symbol, hits in rows
        )
        db.add(
            ScanSummary(
                run_id=run.id,
                market="CN",
                trade_date=target,
                source="fixture",
                adjustment="forward",
                status="success",
                market_regime="unknown",
                universe_count=2,
                scanned_count=2,
                hit_count=2,
                resonance_count=2,
                strategy_hit_counts={},
                sector_strength={},
                filter_counts={},
            )
        )
    report = daily_report(target, "CN", "fixture")
    assert [item["symbol"] for item in report["top_resonance"]] == ["600001.SH", "600000.SH"]
