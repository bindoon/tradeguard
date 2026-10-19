"""
RSI 超卖反弹策略。

条件：
1. RSI 从 30 下方上穿 30。
2. 当日收盘上涨。
3. 成交量高于 20 日均量，避免无量反抽。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.indicators import calculate_rsi, calculate_volume_ma
from tradeguard.screening.strategies.base import BaseSignalStrategy


def detect_rsi_rebound(df: pd.DataFrame, threshold: float = 30) -> bool:
    if len(df) < 2:
        return False

    previous = df.iloc[-2]
    latest = df.iloc[-1]
    if pd.isna(previous.get("rsi")) or pd.isna(latest.get("rsi")):
        return False

    return previous["rsi"] <= threshold < latest["rsi"]


def rsi_rebound_screen(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    result_date: str,
    industry: str = "未知",
) -> Optional[Dict]:
    if df is None or df.empty or len(df) < 25:
        return None

    if "rsi" not in df.columns:
        df = calculate_rsi(df)
    if "volume_ma20" not in df.columns:
        df = calculate_volume_ma(df)

    if not detect_rsi_rebound(df):
        return None

    latest = df.iloc[-1]
    if (
        pd.isna(latest.get("open"))
        or pd.isna(latest.get("close"))
        or pd.isna(latest.get("volume_ma20"))
    ):
        return None
    if latest["close"] <= latest["open"] or latest["volume"] <= latest["volume_ma20"]:
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "latest_price": float(latest["close"]),
        "metadata": {
            "rsi": float(latest["rsi"]),
            "volume": float(latest["volume"]),
            "volume_ma20": float(latest["volume_ma20"]),
        },
    }


class RsiReboundStrategy(BaseSignalStrategy):
    name = "rsi_rebound"
    title = "RSI 超卖反弹"
    description = "RSI 从超卖区上穿 30，且伴随放量阳线。"
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
        return rsi_rebound_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        from tradeguard.screening.indicators import calculate_rsi, calculate_volume_ma

        df = calculate_rsi(df)
        df = calculate_volume_ma(df)
        return df

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Entry: RSI crosses above 30 + bullish candle + volume > volume_ma20."""
        if "rsi" not in df.columns:
            df = self.populate_indicators(df)
        rsi = df["rsi"]
        cross_30 = (rsi.shift(1) <= 30) & (rsi > 30)
        bullish = df["close"] > df["open"]
        volume_ok = df["volume"] > df["volume_ma20"]
        return (cross_30 & bullish & volume_ok).fillna(False)

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Exit: RSI crosses above 70 (overbought)."""
        if "rsi" not in df.columns:
            df = self.populate_indicators(df)
        rsi = df["rsi"]
        return ((rsi.shift(1) <= 70) & (rsi > 70)).fillna(False)


STRATEGY = RsiReboundStrategy()
