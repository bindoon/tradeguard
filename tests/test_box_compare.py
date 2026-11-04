import json
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from tradeguard.backtesting.box_compare import compare_box, summarize_signals
from tradeguard.cli import app
from tradeguard.db import session
from tradeguard.db.models import Run
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars


def test_summary_uses_only_complete_forward_windows():
    event = {
        "strategy": "box_high_breakout",
        "symbol": "600000.SH",
        "close": Decimal("12"),
        "box_top": Decimal("10"),
        "future_closes": [Decimal("15")] * 20,
        "future_highs": [Decimal("16")] * 20,
        "future_lows": [Decimal("11")] * 20,
    }
    short = {
        **event,
        "strategy": "box_breakout",
        "future_closes": [Decimal("9"), Decimal("9")],
        "future_highs": [Decimal("9"), Decimal("9")],
        "future_lows": [Decimal("8"), Decimal("8")],
    }
    rows = {item["strategy"]: item for item in summarize_signals([event, short])}
    high = rows["box_high_breakout"]
    assert high["forward_return"]["5"] == {
        "count": 1,
        "mean": "0.250000",
        "median": "0.250000",
    }
    assert high["forward_return"]["20"]["mean"] == "0.250000"
    assert high["max_favorable_excursion"]["mean"] == "0.333333"
    assert high["max_adverse_excursion"]["mean"] == "-0.083333"
    assert high["false_breakout"] == {"count": 1, "false_count": 0, "rate": "0.000000", "bars": 3}
    old = rows["box_breakout"]
    assert old["forward_return"]["5"]["count"] == 0
    assert old["false_breakout"]["count"] == 0
    assert old["max_favorable_excursion"]["count"] == 0


def test_compare_rejects_a_reversed_range_before_reading():
    with pytest.raises(ValueError, match="--start"):
        compare_box("fixture", date(2026, 2, 1), date(2026, 1, 1))


def _bars(symbol, rows, specs):
    dates = pd.bdate_range("2024-01-02", periods=rows)
    bars = []
    for index, day in enumerate(dates):
        open_, high, low, close, volume = specs(index)
        bars.append(
            BarInput(
                symbol=symbol,
                name=symbol,
                trade_date=day.date(),
                source="fixture",
                adjustment="forward",
                open=Decimal(str(open_)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
                volume=Decimal(str(volume)),
                amount=Decimal("1000000"),
            )
        )
    return dates, bars


def test_compare_box_reads_daily_bars_and_does_not_write(database):
    def wick(index):
        if index == 44:
            return 10, 11, 9.8, 10, 1000
        if index == 49:
            return 10.1, 10.4, 10, 10.2, 3000
        if index == 52:
            return 10, 10.2, 9.4, 9.5, 1000
        if index > 49:
            return 10.2, 10.5, 10.1, 10.3, 1000
        return 10, 10.2, 9.8, 10, 1000

    def genuine(index):
        if index == 49:
            return 11, 12.5, 10.5, 12, 3000
        if index > 49:
            return 14, 16, 11, 15, 1000
        return 10, 10, 9.5, 10, 1000

    dates, left = _bars("600000.SH", 70, wick)
    _, right = _bars("600001.SH", 70, genuine)
    save_bars(left + right, record_run=True)
    signal = dates[49].date()
    with session() as db:
        before = db.scalar(select(func.count()).select_from(Run))
    result = compare_box("fixture", signal, signal, "forward", "CN")
    with session() as db:
        after = db.scalar(select(func.count()).select_from(Run))
    assert after == before
    assert result["read_only"] is True
    by_name = {item["strategy"]: item for item in result["strategies"]}
    assert by_name["box_breakout"]["signals"] == 2
    assert by_name["box_breakout"]["false_breakout"]["false_count"] == 1
    assert by_name["box_breakout"]["false_breakout"]["rate"] == "0.500000"
    assert by_name["box_high_breakout"]["signals"] == 1
    assert by_name["box_high_breakout"]["symbols"] == 1
    assert by_name["box_high_breakout"]["forward_return"]["5"]["mean"] == "0.250000"
    assert by_name["box_high_breakout"]["forward_return"]["10"]["mean"] == "0.250000"
    assert by_name["box_high_breakout"]["forward_return"]["20"]["mean"] == "0.250000"
    assert by_name["box_high_breakout"]["max_favorable_excursion"]["mean"] == "0.333333"
    assert by_name["box_high_breakout"]["max_adverse_excursion"]["mean"] == "-0.083333"
    assert by_name["box_high_breakout"]["false_breakout"]["rate"] == "0.000000"
    runner = CliRunner()
    command = runner.invoke(
        app,
        [
            "backtest",
            "compare-box",
            "--source",
            "fixture",
            "--start",
            str(signal),
            "--end",
            str(signal),
            "--adjustment",
            "forward",
            "--symbol",
            "600001.SH",
        ],
    )
    assert command.exit_code == 0, command.output
    payload = json.loads(command.stdout)
    assert payload["status"] == "success"
    selected = {item["strategy"]: item for item in payload["data"]["strategies"]}
    assert selected["box_high_breakout"]["signals"] == 1
    assert selected["box_breakout"]["signals"] == 1
