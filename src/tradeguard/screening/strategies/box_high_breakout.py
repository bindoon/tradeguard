"""
箱体高点突破确认。Box High Breakout (close-confirmed)。

与箱体突破并排存在，不替换它。箱体突破的上沿是窗口内最高收盘，
会把盘中冲高回落的影线留在箱外。本策略改用最高价、最低价画箱，
再用收盘确认突破。

条件（阈值均可配置，下列为默认值）：
1. 箱体窗口为信号日前 N=20 根，不含信号日。
   box_top 为窗口最高价，box_bottom 为窗口最低价。
2. 振幅 (box_top - box_bottom) / box_bottom 必须严格小于 15%，
   比较方式与箱体突破相同。
3. 收盘确认：当日收盘 >= box_top * (1 + 1%)。
4. 当日成交量 >= 1.5 × 含当日的 20 日均量。
5. 只取首次突破：前一日收盘 <= 前一日自己的高点箱体上沿
   （该上沿是前一日之前 N 根的最高价，不含前一日）。
   信号日的窗口含前一日的最高价，前一日收盘几乎总是不高于该窗口，
   因此首次判断必须看前一日当时的箱体，否则后续交易日会重复发信号。
止损参考：收盘跌破箱体中轨 (box_top + box_bottom) / 2。
"""

from decimal import Decimal
from typing import Any, Dict, Optional

import pandas as pd
from pydantic import Field

from tradeguard.screening.indicators import calculate_volume_ma
from tradeguard.screening.strategies.base import BaseSignalStrategy
from tradeguard.screening.strategies.classics import Parameters

VOLUME_MA_PERIOD = 20


class BoxHighParameters(Parameters):
    box_period: int = Field(
        default=20,
        ge=2,
        le=120,
        title="箱体窗口",
        description="信号日之前的交易日数，不含信号日本身。上沿取这些日线的最高价，下沿取最低价。",
    )
    max_box_range_pct: float = Field(
        default=0.15,
        gt=0,
        le=5,
        title="箱体最大振幅",
        description="小数比例，必须严格小于该值。0.15 表示 15%。算法与箱体突破相同：(上沿-下沿)/下沿。",
    )
    min_breakout_pct: float = Field(
        default=0.01,
        ge=0,
        le=1,
        title="最小突破幅度",
        description="小数比例。0.01 表示收盘至少高于箱体最高价 1% 才确认突破。",
    )
    vol_mult: float = Field(
        default=1.5,
        gt=0,
        le=20,
        title="放量倍数",
        description="当日成交量大于或等于该倍数乘以含当日的 20 日均量。",
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        return None
    return number


def _percent(value: float) -> str:
    number = (Decimal(str(value)) * 100).normalize()
    return format(number, "f") + "%"


def _number(value: Decimal, places: str) -> float:
    return float(value.quantize(Decimal(places)))


def _bar_date(row: pd.Series) -> str | None:
    if "date" not in row.index:
        return None
    value = row["date"]
    if pd.isna(value):
        return None
    return str(value)[:10]


class BoxHighBreakoutStrategy(BaseSignalStrategy):
    name = "box_high_breakout"
    title = "箱体高点突破确认"
    english_name = "Box High Breakout (close-confirmed)"
    description = (
        "横盘整理 20 日后收盘首次放量突破箱体最高价，"
        "箱体振幅 < 15%，收盘高于最高价至少 1%，量能 ≥ 1.5×MA20。"
    )
    parameters_model = BoxHighParameters
    required_days = 120
    min_history = 41

    stoploss = -0.08
    take_profit = 0.15
    max_holding_days = 15

    def __init__(self):
        self.parameters = self.parameters_model()
        self.configure()

    def configure(self) -> None:
        period = self.parameters.box_period
        self.min_history = period + VOLUME_MA_PERIOD + 1
        multiple = format(Decimal(str(self.parameters.vol_mult)), "f")
        self.description = (
            f"横盘整理 {period} 日后收盘首次放量突破箱体最高价，"
            f"箱体振幅 < {_percent(self.parameters.max_box_range_pct)}，"
            f"收盘高于最高价至少 {_percent(self.parameters.min_breakout_pct)}，"
            f"量能 ≥ {multiple}×MA20。"
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        period = self.parameters.box_period
        df = df.copy()
        df["box_top"] = df["high"].shift(1).rolling(window=period).max()
        df["box_bottom"] = df["low"].shift(1).rolling(window=period).min()
        df["box_mid"] = (df["box_top"] + df["box_bottom"]) / 2
        df["box_range_pct"] = (df["box_top"] - df["box_bottom"]) / df["box_bottom"]
        return calculate_volume_ma(df)

    def _top_date(self, prepared: pd.DataFrame, top: Decimal) -> str | None:
        window = prepared.iloc[-(self.parameters.box_period + 1) : -1]
        for offset in range(len(window) - 1, -1, -1):
            row = window.iloc[offset]
            high = _decimal(row["high"])
            if high == top:
                return _bar_date(row)
        return None

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        if df is None or df.empty or len(df) < self.min_history:
            return None
        if not {"high", "low", "close", "volume"}.issubset(df.columns):
            return None
        prepared = self.populate_indicators(df)
        latest = prepared.iloc[-1]
        previous = prepared.iloc[-2]
        top = _decimal(latest["box_top"])
        bottom = _decimal(latest["box_bottom"])
        previous_top = _decimal(previous["box_top"])
        close = _decimal(latest["close"])
        previous_close = _decimal(previous["close"])
        volume = _decimal(latest["volume"])
        volume_ma = _decimal(latest["volume_ma20"])
        required = [top, bottom, previous_top, close, previous_close, volume, volume_ma]
        if any(value is None for value in required):
            return None
        assert top is not None and bottom is not None and previous_top is not None
        assert close is not None and previous_close is not None
        assert volume is not None and volume_ma is not None
        if bottom <= 0 or top <= 0 or volume_ma <= 0:
            return None
        box_range = (top - bottom) / bottom
        if box_range >= Decimal(str(self.parameters.max_box_range_pct)):
            return None
        if close < top * (Decimal(1) + Decimal(str(self.parameters.min_breakout_pct))):
            return None
        # The signal window includes the previous high, so compare the previous
        # close with the box that was already closed before that bar.
        if previous_close > previous_top:
            return None
        if volume < Decimal(str(self.parameters.vol_mult)) * volume_ma:
            return None
        top_date = self._top_date(prepared, top)
        if top_date is None:
            return None
        mid = (top + bottom) / 2
        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "result_date": result_date,
            "industry": industry,
            "latest_price": _number(close, "0.000001"),
            "metadata": {
                "box_top": _number(top, "0.000001"),
                "box_bottom": _number(bottom, "0.000001"),
                "box_mid": _number(mid, "0.000001"),
                "box_period": self.parameters.box_period,
                "box_range_pct": _number(box_range, "0.0001"),
                "breakout_pct": _number(close / top - 1, "0.000001"),
                "volume": _number(volume, "0.0001"),
                "volume_ma20": _number(volume_ma, "0.0001"),
                "volume_ratio": _number(volume / volume_ma, "0.01"),
                "box_top_date": top_date,
                "parameters": self.parameters.model_dump(mode="json"),
            },
        }

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        if "box_mid" not in df.columns:
            df = self.populate_indicators(df)
        close = df["close"]
        return ((close.shift(1) >= df["box_mid"].shift(1)) & (close < df["box_mid"])).fillna(False)


STRATEGY = BoxHighBreakoutStrategy()
