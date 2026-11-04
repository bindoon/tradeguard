"""Explicit long-only daily research variants, all using the same screen contract."""

from decimal import Decimal
from typing import Literal, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradeguard.screening.strategies.base import BaseSignalStrategy


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MovingAverageParameters(Parameters):
    fast: int = Field(
        default=20,
        ge=2,
        le=200,
        title="快线周期",
        description="观察交易日数，较短周期对价格变化更敏感。",
    )
    slow: int = Field(
        default=60, ge=3, le=300, title="慢线周期", description="观察交易日数；必须大于快线。"
    )
    average: Literal["sma", "ema"] = Field(
        default="sma", title="均线类型", description="sma 为简单平均；ema 对近期价格赋予更大权重。"
    )
    trend: int | None = Field(
        default=None,
        ge=4,
        le=350,
        title="长趋势线周期",
        description="可留空；填写时必须大于慢线，并要求慢线高于该趋势线。",
    )

    @model_validator(mode="after")
    def order(self) -> Self:
        if self.fast >= self.slow or (self.trend is not None and self.trend <= self.slow):
            raise ValueError("均线周期必须满足快线 < 慢线 < 可选长趋势线")
        return self


class ChannelParameters(Parameters):
    entry: int = Field(
        default=20,
        ge=2,
        le=300,
        title="突破回看周期",
        description="不含当日的 N 根日线；收盘价超过这些日线的最高价才命中。",
    )
    exit: int = Field(
        default=10,
        ge=2,
        le=300,
        title="退出通道周期",
        description="收盘跌破此前 N 根日线的最低价，产生退出信号。",
    )


class RSIParameters(Parameters):
    period: int = Field(
        default=2,
        ge=2,
        le=30,
        title="RSI 周期",
        description="默认 2 日，用 Wilder 平滑计算短期涨跌强弱。",
    )
    oversold: float = Field(
        default=5,
        gt=0,
        lt=50,
        title="超跌阈值",
        description="RSI 小于或等于此值，并满足长期趋势过滤时命中；单位为 0–100 的 RSI 点数。",
    )
    trend: int = Field(
        default=200,
        ge=10,
        le=350,
        title="趋势均线周期",
        description="要求收盘价高于这条简单均线，研究上升趋势中的短期回调。",
    )
    exit_average: int = Field(
        default=5,
        ge=2,
        le=100,
        title="反弹退出均线周期",
        description="收盘价高于该简单均线时产生退出信号，并不保证该笔交易盈利。",
    )


class BollingerParameters(Parameters):
    window: int = Field(
        default=20,
        ge=3,
        le=300,
        title="布林带周期",
        description="用最近 N 个收盘计算中轨及样本标准差（ddof=1）。",
    )
    deviations: float = Field(
        default=2,
        gt=0,
        le=5,
        title="标准差倍数",
        description="下轨=中轨−倍数×标准差；倍数越大，要求的偏离越大。",
    )
    trend: int | None = Field(
        default=200,
        ge=5,
        le=350,
        title="趋势过滤周期",
        description="可留空；填写时要求当前收盘高于该简单均线。",
    )


class MomentumParameters(Parameters):
    lookback: int = Field(
        default=252,
        ge=2,
        le=350,
        title="收益回看周期",
        description="比较当前收盘与 N 个已观察交易日前收盘，至少需要 N+1 根日线。",
    )
    minimum_return: Decimal = Field(
        default=Decimal(0),
        ge=Decimal("-0.99"),
        le=10,
        title="最低价格收益",
        description="小数比例；0 表示价格上涨才命中，0.05 表示要求超过 5%。不是含分红或扣除无风险利率的超额收益。",
    )


def average(close, period, kind="sma"):
    return (
        close.ewm(span=period, adjust=False, min_periods=period).mean()
        if kind == "ema"
        else close.rolling(period).mean()
    )


def wilder_rsi(close, period):
    """Seed with the first N deltas, then Wilder smoothing; no future/NaN fill."""
    delta = close.diff()
    result = pd.Series(float("nan"), index=close.index)
    if len(close) <= period:
        return result
    gain = float(delta.iloc[1 : period + 1].clip(lower=0).mean())
    loss = float((-delta.iloc[1 : period + 1].clip(upper=0)).mean())
    for i in range(period, len(close)):
        if i > period:
            change = float(delta.iloc[i])
            gain = (gain * (period - 1) + max(change, 0)) / period
            loss = (loss * (period - 1) + max(-change, 0)) / period
        result.iloc[i] = (
            50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
        )
    return result


class ParameterizedSignal(BaseSignalStrategy):
    parameters_model = Parameters

    def __init__(self):
        self.parameters = self.parameters_model()
        self.configure()

    def configure(self):
        raise NotImplementedError

    def conditions(self, frame):
        raise NotImplementedError

    def screen(
        self, stock_code, stock_name, df, result_date, industry="未知", dependency_result=None
    ):
        if len(df) < self.min_history:
            return None
        prepared = self.populate_indicators(df.copy())
        if not bool(self.conditions(prepared).iloc[-1]):
            return None
        latest = prepared.iloc[-1]
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "result_date": result_date,
            "industry": industry,
            "latest_price": float(latest["close"]),
            "metadata": {
                "parameters": self.parameters.model_dump(mode="json"),
                "conditions": self.description,
            },
        }


class MovingAverageCross(ParameterizedSignal):
    name = "moving_average_cross"
    title = "通用均线交叉"
    description = "快线上穿慢线，可选慢线高于长趋势线过滤；快线下穿慢线退出。"
    parameters_model = MovingAverageParameters
    min_history = 61

    def configure(self):
        p = self.parameters
        self.min_history = max(p.fast, p.slow, p.trend or 0) + 1

    def populate_indicators(self, df):
        p = self.parameters
        df["fast_average"] = average(df["close"], p.fast, p.average)
        df["slow_average"] = average(df["close"], p.slow, p.average)
        if p.trend:
            df["trend_average"] = average(df["close"], p.trend, p.average)
        return df

    def conditions(self, df):
        fast, slow = df["fast_average"], df["slow_average"]
        hit = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        return hit & (slow > df["trend_average"]) if self.parameters.trend else hit

    def exit_signal(self, df):
        df = self.populate_indicators(df.copy())
        fast, slow = df["fast_average"], df["slow_average"]
        return ((fast < slow) & (fast.shift(1) >= slow.shift(1))).fillna(False)


class DonchianBreakout(ParameterizedSignal):
    name = "donchian_breakout"
    title = "唐奇安通道突破"
    description = "收盘突破此前 N 日最高价进入，收盘跌破此前 M 日最低价退出；窗口均排除当日。"
    parameters_model = ChannelParameters
    min_history = 21

    def configure(self):
        self.min_history = max(self.parameters.entry, self.parameters.exit) + 1

    def populate_indicators(self, df):
        df["entry_channel"] = df["high"].shift(1).rolling(self.parameters.entry).max()
        df["exit_channel"] = df["low"].shift(1).rolling(self.parameters.exit).min()
        return df

    def conditions(self, df):
        return df["close"] > df["entry_channel"]

    def exit_signal(self, df):
        df = self.populate_indicators(df.copy())
        return (df["close"] < df["exit_channel"]).fillna(False)


class RSI2Reversion(ParameterizedSignal):
    name = "rsi2_reversion"
    title = "短周期 RSI 均值回归"
    description = "长期均线之上出现短期 RSI 超跌，反弹至短均线之上产生退出信号。"
    parameters_model = RSIParameters
    min_history = 200

    def configure(self):
        p = self.parameters
        self.min_history = max(p.trend, p.period + 1, p.exit_average)

    def populate_indicators(self, df):
        p = self.parameters
        df["short_rsi"] = wilder_rsi(df["close"], p.period)
        df["trend_average"] = average(df["close"], p.trend)
        df["exit_average"] = average(df["close"], p.exit_average)
        return df

    def conditions(self, df):
        return (df["close"] > df["trend_average"]) & (df["short_rsi"] <= self.parameters.oversold)

    def exit_signal(self, df):
        df = self.populate_indicators(df.copy())
        return (df["close"] > df["exit_average"]).fillna(False)


class BollingerReversion(ParameterizedSignal):
    name = "bollinger_reversion"
    title = "布林带回归确认"
    description = "前日收盘在下轨之外、当日重新回到下轨内，配合可选长期趋势过滤；回到中轨退出。"
    parameters_model = BollingerParameters
    min_history = 200

    def configure(self):
        p = self.parameters
        self.min_history = max(p.window + 1, p.trend or 0)

    def populate_indicators(self, df):
        p = self.parameters
        df["middle"] = average(df["close"], p.window)
        df["lower"] = df["middle"] - p.deviations * df["close"].rolling(p.window).std(ddof=1)
        if p.trend:
            df["trend_average"] = average(df["close"], p.trend)
        return df

    def conditions(self, df):
        hit = (df["close"].shift(1) < df["lower"].shift(1)) & (df["close"] >= df["lower"])
        return hit & (df["close"] > df["trend_average"]) if self.parameters.trend else hit

    def exit_signal(self, df):
        df = self.populate_indicators(df.copy())
        return (df["close"] >= df["middle"]).fillna(False)


class AbsoluteMomentum(ParameterizedSignal):
    name = "absolute_momentum"
    title = "绝对动量（价格版）"
    description = "当前收盘相对 N 日前的价格收益严格超过门槛才命中，跌至门槛或以下产生退出信号。"
    parameters_model = MomentumParameters
    min_history = 253

    def configure(self):
        self.min_history = self.parameters.lookback + 1

    def populate_indicators(self, df):
        n = self.parameters.lookback
        df["price_momentum"] = pd.Series(
            [
                None
                if i < n
                else Decimal(str(df.iloc[i]["close"])) / Decimal(str(df.iloc[i - n]["close"])) - 1
                for i in range(len(df))
            ],
            index=df.index,
            dtype=object,
        )
        return df

    def conditions(self, df):
        return df["price_momentum"].map(
            lambda value: value is not None and value > self.parameters.minimum_return
        )

    def exit_signal(self, df):
        df = self.populate_indicators(df.copy())
        return df["price_momentum"].map(
            lambda value: value is not None and value <= self.parameters.minimum_return
        )


CLASSIC_SIGNALS = [
    MovingAverageCross(),
    DonchianBreakout(),
    RSI2Reversion(),
    BollingerReversion(),
    AbsoluteMomentum(),
]
