from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradeguard.market.schemas import currency_for, normalize_symbol
from tradeguard.screening.availability import today


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SignalSpec(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    lookback: int = Field(default=1, ge=1, le=60)


class Combination(StrictModel):
    signals: list[SignalSpec] = Field(min_length=1, max_length=20)
    mode: Literal["all", "any", "at_least"] = "all"
    minimum: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def distinct(self) -> Self:
        names = [item.name for item in self.signals]
        if len(set(names)) != len(names):
            raise ValueError("组合内信号不可重复")
        if self.minimum > len(names):
            raise ValueError("共振门槛超过信号数")
        return self


class Execution(StrictModel):
    commission: Decimal = Field(ge=0, le=Decimal("0.1"))
    minimum_commission: Decimal = Field(ge=0)
    sell_tax: Decimal = Field(ge=0, le=Decimal("0.1"))
    slippage_bps: Decimal = Field(ge=0, le=1000)
    lot_size: int = Field(ge=1, le=100000)
    settlement_days: int = Field(ge=0, le=10)
    # An explicit research model, not an exchange's verified daily limit price.
    limit_pct: Decimal | None = Field(default=None, gt=0, le=1)
    prior_volume_fraction: Decimal = Field(default=Decimal("0.01"), gt=0, le=1)


class Exits(StrictModel):
    stop_loss: Decimal | None = Field(default=None, gt=0, lt=1)
    take_profit: Decimal | None = Field(default=None, gt=0)
    trailing_stop: Decimal | None = Field(default=None, gt=0, lt=1)
    max_holding_days: int | None = Field(default=None, ge=1, le=10000)
    signal_exit: bool = False


class BacktestConfig(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    market: Literal["CN", "US", "HK"]
    currency: Literal["CNY", "USD", "HKD"]
    source: str = Field(min_length=1, max_length=40)
    adjustment: Literal["none", "forward", "backward"]
    price_model: Literal["adjusted_research", "raw_without_actions"]
    frequency: Literal["1d"] = "1d"
    start: date
    end: date
    symbols: list[str] = Field(min_length=1, max_length=500)
    benchmark: str | None = None
    initial_cash: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    combination: Combination | None = None
    portfolio_strategy: str = "signal_portfolio"
    strategy_parameters: dict[str, Any] = Field(default_factory=dict)
    max_positions: int = Field(default=5, ge=1, le=500)
    max_weight: Decimal = Field(default=Decimal("0.2"), gt=0, le=1)
    invested_fraction: Decimal = Field(default=Decimal("0.95"), gt=0, le=1)
    rank_by: Literal["hits", "momentum", "symbol"] = "hits"
    schedule: Literal["daily", "weekly", "monthly"] = "daily"
    rebalance: bool = False
    missing_data: Literal["error", "skip_with_warning"] = "error"
    execution: Execution
    exits: Exits = Field(default_factory=Exits)

    @field_validator("symbols")
    @classmethod
    def normalize(cls, values: list[str]) -> list[str]:
        result = [normalize_symbol(value) for value in values]
        if len(set(result)) != len(result):
            raise ValueError("股票池包含重复代码")
        return sorted(result)

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, value: str | None) -> str | None:
        return normalize_symbol(value) if value else None

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if self.portfolio_strategy == "signal_portfolio" and self.combination is None:
            raise ValueError("信号组合交易策略至少需要一个信号")
        if self.exits.signal_exit and self.combination is None:
            raise ValueError("没有信号组合时，不能启用基础信号退出")
        if self.start >= self.end or self.end > today():
            raise ValueError("回测区间必须至少两天，且不能包含未来日期")
        if (self.end - self.start).days > 365 * 30:
            raise ValueError("单次回测最多 30 年")
        expected = {"CN": "CNY", "US": "USD", "HK": "HKD"}[self.market]
        if self.currency != expected:
            raise ValueError("币种与市场不符；跨币种回测需要显式 FX，当前未支持")
        for symbol in self.symbols + ([self.benchmark] if self.benchmark else []):
            if currency_for(symbol) != expected:
                raise ValueError("股票池和基准必须属于所选市场")
        if (self.adjustment == "none") != (self.price_model == "raw_without_actions"):
            raise ValueError("原始价与复权研究模型不匹配")
        return self
