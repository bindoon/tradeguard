"""Acceptance: cash, causal time, frozen evidence, and the CLI/HTTP report journey."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from tradeguard.backtesting import engine, plugins, service
from tradeguard.backtesting.plugins import PortfolioStrategy
from tradeguard.backtesting.schemas import BacktestConfig
from tradeguard.backtesting.strategy import SignalPortfolio
from tradeguard.cli import app
from tradeguard.console import create_app
from tradeguard.db import session
from tradeguard.db.models import BacktestArtifact, DailyBar, PortfolioSnapshot
from tradeguard.market.schemas import BarInput
from tradeguard.market.service import save_bars
from tradeguard.screening.strategies.base import BaseSignalStrategy
from tradeguard.screening.strategies.ma_golden_cross import STRATEGY as MA


class TestSignal(BaseSignalStrategy):
    __test__ = False
    name = "acceptance_signal"
    title = "合成验收信号"
    description = "仅用于合成数据验收"
    min_history = 1

    def screen(
        self, stock_code, stock_name, df, result_date, industry="未知", dependency_result=None
    ):
        return {"metadata": {"close": float(df.iloc[-1]["close"])}}


class Rotation(PortfolioStrategy):
    name = "acceptance_rotation"
    title = "合成调仓"

    def on_close(self, context):
        # Reads only a causal copy, and this instance carries its own state.
        assert context.history(context.universe[0]).iloc[-1]["date"] == context.current_date
        self.count = getattr(self, "count", 0) + 1
        return {
            symbol: Decimal("0.5") if self.count == 1 else Decimal(0) for symbol in context.universe
        }


def config(**overrides):
    return BacktestConfig.model_validate(
        {
            "name": "合成多股票实验",
            "market": "CN",
            "currency": "CNY",
            "source": "fixture",
            "adjustment": "none",
            "price_model": "raw_without_actions",
            "start": "2025-01-06",
            "end": "2025-01-09",
            "symbols": ["600000.SH", "600001.SH"],
            "initial_cash": "10000",
            "combination": {"signals": [{"name": TestSignal.name}], "mode": "all"},
            "max_positions": 2,
            "max_weight": "0.5",
            "invested_fraction": "1",
            "execution": {
                "commission": "0",
                "minimum_commission": "0",
                "sell_tax": "0",
                "slippage_bps": "0",
                "lot_size": 100,
                "settlement_days": 1,
                "prior_volume_fraction": "1",
            },
            **overrides,
        }
    )


def slices():
    return {
        symbol: {
            "symbol": symbol,
            "name": "Synthetic",
            "market": "CN",
            "currency": "CNY",
            "bars": [
                {
                    "date": "2025-01-0" + str(day),
                    "open": str(price),
                    "high": str(price),
                    "low": str(price),
                    "close": str(price),
                    "volume": "100000",
                    "amount": None,
                }
                for day, price in [(6, 10), (7, 10), (8, 12), (9, 12)]
            ],
        }
        for symbol in config().symbols
    }


def replay_engine(cfg=None, inputs=None, strategy=None):
    return engine.run(
        cfg or config(),
        inputs or slices(),
        {"calendar": ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"], "warnings": []},
        {TestSignal.name: TestSignal()},
        strategy or SignalPortfolio(),
    )


def test_multiple_stocks_share_cash_and_signals_execute_next_open():
    report = replay_engine()
    assert [(t["symbol"], t["date"], t["quantity"]) for t in report["trades"]] == [
        ("600000.SH", "2025-01-07", 500),
        ("600001.SH", "2025-01-07", 500),
    ]
    assert Decimal(report["metrics"]["final_equity"]) == 12000
    assert Decimal(report["metrics"]["total_return"]) == Decimal("0.2")
    assert report["metrics"]["benchmark_return"] is None
    assert report["metrics"]["annualized_return"] is None
    assert report["metrics"]["sharpe_zero_rf"] is None
    for point in report["curve"]:
        assert Decimal(point["cash"]) >= 0
        assert Decimal(point["equity"]) == Decimal(point["cash"]) + sum(
            Decimal(pos["value"]) for pos in point["holdings"]
        )
    assert replay_engine()["result_hash"] == report["result_hash"]


def test_fees_minimum_commission_and_slippage_never_overdraw():
    cfg = config(
        execution={
            "commission": "0.001",
            "minimum_commission": "5",
            "sell_tax": "0.001",
            "slippage_bps": "10",
            "lot_size": 100,
            "settlement_days": 1,
            "prior_volume_fraction": "1",
        }
    )
    report = replay_engine(cfg, strategy=Rotation())
    buys = [t for t in report["trades"] if t["side"] == "buy"]
    sells = [t for t in report["trades"] if t["side"] == "sell"]
    assert len(buys) == len(sells) == 2
    assert Decimal(buys[0]["price"]) == Decimal("10.010")
    assert Decimal(sells[0]["price"]) == Decimal("11.988")
    assert all(Decimal(p["cash"]) >= 0 for p in report["curve"])
    expected = cfg.initial_cash - sum(Decimal(t["notional"]) + Decimal(t["fee"]) for t in buys)
    expected += sum(Decimal(t["notional"]) - Decimal(t["fee"]) for t in sells)
    assert Decimal(report["metrics"]["final_equity"]) == expected
    assert report["positions"] == []


def test_execution_uses_next_open_without_reading_that_days_close():
    inputs = slices()
    for value in inputs.values():
        value["bars"][1].update(open="10", low="10", high="20", close="20")
    report = replay_engine(inputs=inputs)
    assert [Decimal(trade["price"]) for trade in report["trades"]] == [Decimal(10), Decimal(10)]
    assert [trade["quantity"] for trade in report["trades"]] == [500, 500]
    assert Decimal(report["curve"][1]["equity"]) == Decimal(20000)
    assert all(trade["date"] > trade["signal_date"] for trade in report["trades"])


def test_signal_lookback_includes_frozen_warmup_before_start():
    class PriorSignal(TestSignal):
        name = "prior_signal"

        def screen(self, **kwargs):
            return {"metadata": {}} if kwargs["result_date"] == "2025-01-03" else None

    inputs = slices()
    for value in inputs.values():
        value["bars"].insert(0, {**value["bars"][0], "date": "2025-01-03"})
    cfg = config(combination={"signals": [{"name": "prior_signal", "lookback": 2}]})
    report = engine.run(
        cfg,
        inputs,
        {"calendar": ["2025-01-06", "2025-01-07"], "warnings": []},
        {"prior_signal": PriorSignal()},
        SignalPortfolio(),
    )
    assert len(report["trades"]) == 2
    assert all(trade["signal_date"] == "2025-01-06" for trade in report["trades"])


@pytest.mark.parametrize(
    "mode,minimum,expected", [("all", 1, 0), ("any", 1, 2), ("at_least", 1, 2), ("at_least", 2, 0)]
)
def test_combinations_only_buy_when_threshold_is_proven(mode, minimum, expected):
    class NeverSignal(TestSignal):
        name = "never"

        def screen(self, **kwargs):
            return None

    class UnknownSignal(TestSignal):
        name = "unknown"
        min_history = 1000

    signals = {item.name: item for item in [TestSignal(), NeverSignal(), UnknownSignal()]}
    cfg = config(
        combination={
            "mode": mode,
            "minimum": minimum,
            "signals": [{"name": name} for name in signals],
        }
    )
    report = engine.run(
        cfg,
        slices(),
        {"calendar": ["2025-01-06", "2025-01-07"], "warnings": []},
        signals,
        SignalPortfolio(),
    )
    assert len(report["trades"]) == expected


def test_benchmark_requires_complete_explicit_series():
    ready = replay_engine(config(benchmark="600000.SH"))
    assert Decimal(ready["metrics"]["benchmark_return"]) == Decimal("0.2")
    assert Decimal(ready["metrics"]["excess_return"]) == 0
    absent = replay_engine(config(benchmark="600519.SH"))
    assert absent["metrics"]["benchmark_return"] is None
    assert all(point["benchmark_equity"] is None for point in absent["curve"])


def test_missing_bar_suspension_volume_and_settlement_have_reasons():
    inputs = slices()
    inputs["600000.SH"]["bars"][1]["volume"] = "0"
    inputs["600001.SH"]["bars"].pop(1)
    report = replay_engine(inputs=inputs)
    assert report["orders"][0]["execution_reason"] == "suspended_or_invalid_price"
    assert report["orders"][1]["execution_reason"] == "missing_bar"
    cfg = config(execution={**config().execution.model_dump(), "settlement_days": 3})
    report = replay_engine(cfg, strategy=Rotation())
    assert any(order["execution_reason"] == "settlement_wait" for order in report["orders"])
    assert not [trade for trade in report["trades"] if trade["side"] == "sell"]


def test_stop_at_close_sells_next_day_and_last_orders_expire():
    inputs = slices()
    for value in inputs.values():
        value["bars"][2].update(open="8", high="8", low="8", close="8")
    cfg = config(exits={"stop_loss": "0.1"})
    report = replay_engine(cfg, inputs)
    sells = [t for t in report["trades"] if t["side"] == "sell"]
    assert len(sells) == 2
    assert all(t["signal_date"] == "2025-01-08" and t["date"] == "2025-01-09" for t in sells)
    assert report["orders"][-1]["execution_reason"] == "end_of_test"


def test_unknown_warmup_is_not_a_false_signal_and_history_cannot_see_future():
    cfg = config()
    signal = TestSignal()
    signal.min_history = 100
    context = engine.Context(cfg, slices(), {signal.name: signal})
    context.current_date = "2025-01-06"
    context._calendar = [context.current_date]
    assert len(context.history("600000.SH")) == 1
    assert context.signal(signal.name, "600000.SH") is None
    report = engine.run(
        cfg,
        slices(),
        {"calendar": ["2025-01-06", "2025-01-07"], "warnings": []},
        {signal.name: signal},
        SignalPortfolio(),
    )
    assert not report["trades"] and report["unknown_signal_count"] == 4
    with pytest.raises(ValueError, match="股票池外"):
        context.history("AAPL.US")


def test_entry_adapter_preserves_scanner_two_days_ago_cross():
    from test_strategy_parity import frame

    bars = frame()
    bars["ma5"], bars["ma10"], bars["ma20"], bars["ma60"] = 9.0, 10.0, 11.0, 12.0
    bars.loc[bars.index[-4], ["ma5", "ma10"]] = [10, 10]
    bars.loc[bars.index[-3], ["ma5", "ma10"]] = [11, 10]
    bars.loc[bars.index[-1], ["ma5", "ma10", "ma20", "ma60"]] = [14, 13, 12, 11]
    assert bool(MA.entry_signal(bars).iloc[-1])
    assert MA.screen("600000.SH", "Test", bars, bars.iloc[-1]["date"]) is not None
    future = bars.iloc[-1:].copy()
    future["date"] = "2099-01-01"
    extended = pd.concat([bars, future], ignore_index=True)
    pd.testing.assert_series_equal(
        MA.entry_signal(bars), MA.entry_signal(extended).iloc[: len(bars)]
    )


@pytest.fixture
def installed(monkeypatch):
    def entries(group):
        cls = TestSignal if group == "tradeguard.signals" else Rotation
        return [SimpleNamespace(name=cls.name, load=lambda: cls)]

    monkeypatch.setattr(plugins, "entry_points", entries)


def seed():
    save_bars(
        [
            BarInput.model_validate(
                {
                    "symbol": symbol,
                    "name": "Synthetic",
                    "source": "fixture",
                    "adjustment": "none",
                    "trade_date": bar["date"],
                    **{key: value for key, value in bar.items() if key != "date"},
                }
            )
            for symbol, value in slices().items()
            for bar in value["bars"]
        ]
    )


def test_frozen_replay_plugins_cli_and_http_report(database, installed, tmp_path):
    command.check(Config("alembic.ini"))
    seed()
    cfg = config()
    path = tmp_path / "experiment.json"
    path.write_text(cfg.model_dump_json())
    runner = CliRunner()
    result = runner.invoke(app, ["backtest", "run", "--file", str(path)])
    assert result.exit_code == 0, result.output
    experiment = json.loads(result.output)["data"]
    assert experiment["report"]["metrics"]["trade_count"] == 2
    saved_report = experiment["report"]
    listed = runner.invoke(
        app, ["backtest", "list", "--market", "CN", "--source", "fixture", "--adjustment", "none"]
    )
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["data"]["experiments"][0]["id"] == experiment["id"]
    client = TestClient(create_app())
    scope = "?market=CN&source=fixture&adjustment=none"
    assert client.get("/api/backtests" + scope).json()[0]["id"] == experiment["id"]
    assert client.get(f"/api/backtests/{experiment['id']}" + scope).json()["report"] == saved_report
    assert (
        client.get(
            f"/api/backtests/{experiment['id']}?market=US&source=fixture&adjustment=none"
        ).status_code
        == 404
    )
    assert client.get("/api/backtests?market=CN&source=other&adjustment=none").json() == []
    assert (
        client.patch(
            f"/api/backtests/plugins/{TestSignal.name}", json={"enabled": False}
        ).status_code
        == 200
    )
    with pytest.raises(ValueError, match="禁用"):
        service.create(cfg)
    # Mutating the current cache cannot alter a frozen report or replay.
    with session() as db, db.begin():
        row = db.get(DailyBar, ("600000.SH", date(2025, 1, 9), "fixture", "none"))
        row.open = row.high = row.low = row.close = Decimal(99)
    replayed = runner.invoke(app, ["backtest", "replay", "--run", experiment["id"]])
    assert replayed.exit_code == 0, replayed.output
    replay = json.loads(replayed.output)["data"]
    assert replay["report"] == saved_report
    assert service.get(experiment["id"])["report"] == saved_report
    with session() as db:
        assert db.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(BacktestArtifact)) == 6


def test_preflight_rejects_gaps_and_wrong_scope_without_fetching(database, installed):
    seed()
    with session() as db, db.begin():
        db.delete(db.get(DailyBar, ("600001.SH", date(2025, 1, 7), "fixture", "none")))
    with pytest.raises(ValueError, match="缺口"):
        service.preflight(config())
    preflight = service.preflight(config(missing_data="skip_with_warning"))
    assert preflight["manifest"]["gaps"][0]["missing"] == ["2025-01-07"]
    with pytest.raises(ValueError, match="至少需要"):
        service.preflight(config(source="another_source"))
    with pytest.raises(ValueError, match="必须属于"):
        config(symbols=["AAPL.US"])
    with pytest.raises(ValueError):
        config(frequency="tick")


def test_plugins_are_discovered_by_scanner_and_disable_applies_to_new_scans(database, installed):
    from pathlib import Path

    from tradeguard.market.service import import_csv
    from tradeguard.screening.service import scan

    imported = import_csv(Path("examples/bars.csv"))
    target = date.fromisoformat(imported["max_date"])
    result = scan(target, "synthetic", strategy_names=[TestSignal.name])
    assert result["strategies"] == [TestSignal.name]
    assert result["candidates"][0]["hits"] == [TestSignal.name]
    plugins.set_enabled(TestSignal.name, False)
    with pytest.raises(ValueError, match="禁用"):
        scan(target, "synthetic", strategy_names=[TestSignal.name])


def test_nondeterministic_replay_is_failed_without_publishing_a_report(
    database, installed, monkeypatch
):
    from tradeguard.db.models import Run

    seed()
    original = service.run(config())
    run_engine = engine.run

    def corrupted(*args, **kwargs):
        report = run_engine(*args, **kwargs)
        report["result_hash"] = "0" * 64
        return report

    monkeypatch.setattr(engine, "run", corrupted)
    with pytest.raises(ValueError, match="重放结果不一致"):
        service.replay(original["id"])
    with session() as db:
        failed = db.scalar(
            select(Run).where(Run.details["replay_of"].as_string() == original["id"])
        )
        assert failed.status == "failed"
        assert db.get(BacktestArtifact, (failed.id, "report")) is None
    assert service.get(original["id"])["status"] == "success"
