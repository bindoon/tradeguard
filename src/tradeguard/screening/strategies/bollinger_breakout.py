"""
布林带放量突破策略。

条件：
1. 当日收盘价突破上轨。
2. 前一日仍在上轨下方，避免连续追涨重复入选。
3. 当日成交量高于 20 日均量。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.indicators import calculate_bollinger_bands, calculate_volume_ma
from tradeguard.screening.strategies.base import BaseSignalStrategy


def detect_bollinger_breakout(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False

    previous = df.iloc[-2]
    latest = df.iloc[-1]
    required_values = [
        previous.get("close"),
        previous.get("bb_upper"),
        latest.get("close"),
        latest.get("bb_upper"),
    ]
    if any(pd.isna(value) for value in required_values):
        return False

    return previous["close"] <= previous["bb_upper"] and latest["close"] > latest["bb_upper"]


def bollinger_breakout_screen(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    result_date: str,
    industry: str = "未知",
) -> Optional[Dict]:
    if df is None or df.empty or len(df) < 25:
        return None

    if "bb_upper" not in df.columns:
        df = calculate_bollinger_bands(df)
    if "volume_ma20" not in df.columns:
        df = calculate_volume_ma(df)

    if not detect_bollinger_breakout(df):
        return None

    latest = df.iloc[-1]
    if pd.isna(latest.get("volume_ma20")) or latest["volume"] <= latest["volume_ma20"]:
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "latest_price": float(latest["close"]),
        "metadata": {
            "bb_upper": float(latest["bb_upper"]),
            "bb_middle": float(latest["bb_middle"]),
            "bb_lower": float(latest["bb_lower"]),
            "volume": float(latest["volume"]),
            "volume_ma20": float(latest["volume_ma20"]),
        },
    }


class BollingerBreakoutStrategy(BaseSignalStrategy):
    name = "bollinger_breakout"
    title = "布林带放量突破"
    description = "收盘首次突破布林上轨，且伴随放量。"
    required_days = 120
    min_history = 25

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        return bollinger_breakout_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        from tradeguard.screening.indicators import calculate_bollinger_bands, calculate_volume_ma

        df = calculate_bollinger_bands(df)
        df = calculate_volume_ma(df)
        return df

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Entry: close breaks above bb_upper + volume > volume_ma20."""
        if "bb_upper" not in df.columns:
            df = self.populate_indicators(df)
        close = df["close"]
        breakout = (close.shift(1) <= df["bb_upper"].shift(1)) & (close > df["bb_upper"])
        volume_ok = df["volume"] > df["volume_ma20"]
        return (breakout & volume_ok).fillna(False)

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Exit: close drops below bb_middle."""
        if "bb_upper" not in df.columns:
            df = self.populate_indicators(df)
        close = df["close"]
        return ((close.shift(1) >= df["bb_middle"].shift(1)) & (close < df["bb_middle"])).fillna(
            False
        )


STRATEGY = BollingerBreakoutStrategy()
