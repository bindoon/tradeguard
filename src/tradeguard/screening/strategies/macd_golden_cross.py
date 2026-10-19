"""
MACD 金叉趋势策略。

条件：
1. 当日 MACD 线上穿 Signal 线。
2. MACD 位于零轴上方，过滤弱反弹。
3. 收盘价站上 MA20，确认趋势方向。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.indicators import calculate_macd, calculate_moving_averages
from tradeguard.screening.strategies.base import BaseSignalStrategy


def detect_macd_golden_cross(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False

    previous = df.iloc[-2]
    latest = df.iloc[-1]

    required_values = [
        previous.get("macd"),
        previous.get("macd_signal"),
        latest.get("macd"),
        latest.get("macd_signal"),
    ]
    if any(pd.isna(value) for value in required_values):
        return False

    return previous["macd"] <= previous["macd_signal"] and latest["macd"] > latest["macd_signal"]


def macd_golden_cross_screen(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    result_date: str,
    industry: str = "未知",
) -> Optional[Dict]:
    if df is None or df.empty or len(df) < 35:
        return None

    if "ma20" not in df.columns:
        df = calculate_moving_averages(df)
    if "macd" not in df.columns or "macd_signal" not in df.columns:
        df = calculate_macd(df)

    if not detect_macd_golden_cross(df):
        return None

    latest = df.iloc[-1]
    if pd.isna(latest.get("ma20")) or pd.isna(latest.get("close")):
        return None
    if latest["macd"] <= 0 or latest["close"] <= latest["ma20"]:
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "latest_price": float(latest["close"]),
        "metadata": {
            "macd": float(latest["macd"]),
            "macd_signal": float(latest["macd_signal"]),
            "macd_hist": float(latest["macd_hist"]),
            "ma20": float(latest["ma20"]),
        },
    }


class MacdGoldenCrossStrategy(BaseSignalStrategy):
    name = "macd_golden_cross"
    title = "MACD 金叉趋势"
    description = "当日 MACD 金叉，且位于零轴上方并站上 MA20。"
    required_days = 120
    min_history = 35

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        return macd_golden_cross_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        from tradeguard.screening.indicators import calculate_macd, calculate_moving_averages

        df = calculate_moving_averages(df)
        df = calculate_macd(df)
        return df

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Entry: MACD crosses above signal + MACD > 0 + close > MA20."""
        if "macd" not in df.columns:
            df = self.populate_indicators(df)
        macd = df["macd"]
        signal = df["macd_signal"]
        cross = (macd.shift(1) <= signal.shift(1)) & (macd > signal)
        above_zero = macd > 0
        above_ma20 = df["close"] > df["ma20"]
        return (cross & above_zero & above_ma20).fillna(False)

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Exit: MACD death-crosses below signal."""
        if "macd" not in df.columns:
            df = self.populate_indicators(df)
        macd = df["macd"]
        signal = df["macd_signal"]
        return ((macd.shift(1) >= signal.shift(1)) & (macd < signal)).fillna(False)


STRATEGY = MacdGoldenCrossStrategy()
