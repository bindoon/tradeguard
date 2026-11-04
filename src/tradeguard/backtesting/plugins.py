"""Trusted installed Python plugins. No source code is accepted over HTTP."""

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import StrategyPluginState, now
from tradeguard.screening import indicators
from tradeguard.screening.strategies.base import BaseSignalStrategy
from tradeguard.screening.strategies.registry import STRATEGY_REGISTRY


class NoParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioStrategy:
    """Subclass in an installed entry point; return desired weights at a closed bar.

    A new instance belongs to one run. Keep private strategy state on this instance.
    Context only exposes data through its logical close and immutable position views.
    """

    name = ""
    title = ""
    parameters_model: type[BaseModel] = NoParameters
    parameters: Any
    uses_signals = True
    min_history = 1

    def validate_config(self, config) -> None:
        pass

    def initialize(self, context) -> None:
        pass

    def on_close(self, context) -> dict:
        raise NotImplementedError


@dataclass
class Plugin:
    name: str
    title: str
    kind: str
    factory: Any

    def create(self, parameters: dict):
        model = getattr(self.factory, "parameters_model", NoParameters)
        validated = model.model_validate(parameters)
        instance = self.factory()
        instance.parameters = validated
        if configure := getattr(instance, "configure", None):
            configure()
        return instance

    def snapshot(self) -> dict:
        from tradeguard.backtesting.education import guide_for

        module = inspect.getmodule(self.factory)
        if module is None:
            raise ValueError(f"插件 {self.name} 无法保存代码版本")
        source = inspect.getsource(module)
        # Helpers in separate packages must expose a version and increment it on change.
        version = str(getattr(self.factory, "version", "1"))
        digest = hashlib.sha256(
            (
                source
                + version
                + inspect.getsource(indicators)
                + inspect.getsource(BaseSignalStrategy)
            ).encode()
        ).hexdigest()
        return {
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "version": version,
            "hash": digest,
            "min_history": getattr(self.factory, "min_history", 1),
            "parameters_schema": getattr(
                self.factory, "parameters_model", NoParameters
            ).model_json_schema(),
            "education": deepcopy(getattr(self.factory, "learning_guide", None))
            or guide_for(self.name),
            "default_parameters": {
                name: field["default"]
                for name, field in getattr(self.factory, "parameters_model", NoParameters)
                .model_json_schema()
                .get("properties", {})
                .items()
                if "default" in field
            },
        }


def discover() -> dict[str, Plugin]:
    from tradeguard.backtesting.classic_portfolios import PORTFOLIOS
    from tradeguard.backtesting.strategy import SignalPortfolio

    found = {
        name: Plugin(name, strategy.title, "signal", type(strategy))
        for name, strategy in STRATEGY_REGISTRY.items()
    }
    found["signal_portfolio"] = Plugin(
        "signal_portfolio", "信号组合与仓位管理", "portfolio", SignalPortfolio
    )
    for factory in PORTFOLIOS:
        found[factory.name] = Plugin(factory.name, factory.title, "portfolio", factory)
    for group, kind, base in [
        ("tradeguard.signals", "signal", BaseSignalStrategy),
        ("tradeguard.portfolio_strategies", "portfolio", PortfolioStrategy),
    ]:
        for entry in entry_points(group=group):
            factory = entry.load()
            if not inspect.isclass(factory) or not issubclass(factory, base):
                raise ValueError(f"插件 {entry.name} 必须继承 {base.__name__}")
            name = getattr(factory, "name", "")
            if not name or name in found:
                raise ValueError(f"插件 ID 无效或重复：{name}")
            found[name] = Plugin(name, getattr(factory, "title", "") or name, kind, factory)
    return found


def catalog() -> list[dict]:
    with session() as db:
        states = {item.name: item.enabled for item in db.scalars(select(StrategyPluginState))}
    return [
        {
            **plugin.snapshot(),
            "title": plugin.title,
            "enabled": states.get(plugin.name, True),
            "parameters_schema": getattr(
                plugin.factory, "parameters_model", NoParameters
            ).model_json_schema(),
            "min_history": getattr(plugin.factory, "min_history", 0),
            "dependency": (
                vars(plugin.factory.dependency)
                if getattr(plugin.factory, "dependency", None)
                else None
            ),
            "frequency": "1d",
            "uses_signals": getattr(plugin.factory, "uses_signals", True),
        }
        for plugin in discover().values()
    ]


def set_enabled(name: str, enabled: bool) -> dict:
    if name not in discover():
        raise ValueError("策略插件不存在或未安装")
    from tradeguard.db.write import upsert

    with session() as db, db.begin():
        db.execute(
            upsert(
                StrategyPluginState,
                [{"name": name, "enabled": enabled, "updated_at": now()}],
                ["enabled", "updated_at"],
            )
        )
    return {"name": name, "enabled": enabled}


def resolve(config, *, frozen: list[dict] | None = None):
    installed = discover()
    requested = {spec.name for spec in config.combination.signals} if config.combination else set()
    requested.add(config.portfolio_strategy)
    # Include transitive dependencies in both enablement and code snapshots.
    visited: set[str] = set()

    def visit(name, stack):
        if name in stack:
            raise ValueError("策略依赖存在循环")
        plugin = installed.get(name)
        if plugin is None:
            raise ValueError(f"策略插件未安装：{name}")
        dependency = getattr(plugin.factory, "dependency", None)
        if dependency:
            visit(dependency.strategy_name, stack | {name})
        visited.add(name)

    for name in requested:
        visit(name, set())
    versions = [installed[name].snapshot() for name in sorted(visited)]
    if frozen is not None:
        if versions != frozen:
            raise ValueError("插件代码版本已变化；保留旧报告，重放需恢复原版本")
    else:
        enabled = {item["name"]: item["enabled"] for item in catalog()}
        if disabled := sorted(name for name in visited if not enabled[name]):
            raise ValueError("策略已禁用：" + ", ".join(disabled))
    signals = {}
    params = (
        {spec.name: spec.parameters for spec in config.combination.signals}
        if config.combination
        else {}
    )
    for name in sorted(visited):
        plugin = installed[name]
        if name == config.portfolio_strategy:
            if plugin.kind != "portfolio":
                raise ValueError("交易策略必须是 portfolio 插件")
        elif plugin.kind != "signal":
            raise ValueError("信号组合必须使用 signal 插件")
        else:
            signals[name] = plugin.create(params.get(name, {}))
    strategy = installed[config.portfolio_strategy].create(config.strategy_parameters)
    strategy.validate_config(config)
    for instance in [*signals.values(), strategy]:
        if getattr(instance, "min_history", 0) > 400:
            raise ValueError("策略预热超过当前 400 根历史窗口，不能用截断数据运行")
    return signals, strategy, versions


def scan_plugins(names: list[str], *, explicit: bool = False):
    """Reuse trusted discovery and enablement for the ordinary scanner too."""
    installed = discover()
    states = {item["name"]: item["enabled"] for item in catalog()}
    selected = []
    all_signals: dict[str, BaseSignalStrategy] = {}

    def load(name, stack):
        if name in stack:
            raise ValueError("策略依赖存在循环")
        plugin = installed.get(name)
        if plugin is None or plugin.kind != "signal":
            raise ValueError(f"信号插件不存在：{name}")
        if not states[name]:
            raise ValueError(f"策略已禁用：{name}")
        instance = all_signals.setdefault(name, plugin.create({}))
        if dependency := instance.dependency:
            load(dependency.strategy_name, stack | {name})
        return instance

    for name in dict.fromkeys(names):
        if not explicit and not states.get(name, False):
            continue
        selected.append(load(name, set()))
    if not selected:
        raise ValueError("没有启用的扫描策略")
    return selected, all_signals


def signal_at(strategy, frame: pd.DataFrame, symbol: str, name: str, strategies: dict):
    """The scanner's screen() is the sole entry definition. Unknown stays None."""
    if len(frame) < strategy.min_history:
        return None
    dependency_result = None
    if dependency := strategy.dependency:
        if len(frame) <= dependency.days_ago:
            return None
        previous = frame.iloc[: -dependency.days_ago].copy()
        parent = strategies[dependency.strategy_name]
        evidence = signal_at(parent, previous, symbol, name, strategies)
        if evidence is None:
            return None
        if not evidence["hit"]:
            return {"hit": False, "reason": "前置信号未命中", "metadata": {}}
        dependency_result = {"target_date": str(previous.iloc[-1]["date"])}
    result = strategy.screen(
        stock_code=symbol,
        stock_name=name,
        df=frame.tail(400).copy(),
        result_date=str(frame.iloc[-1]["date"]),
        # Historical sector/classification is deliberately unavailable.
        industry="未知",
        dependency_result=dependency_result,
    )
    return {
        "hit": result is not None,
        "reason": strategy.description,
        "metadata": deepcopy(result.get("metadata", {})) if result else {},
    }


def canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()
