"""
箱体突破策略。

条件：
1. 过去 BOX_PERIOD 日（不含当日）收盘价在一个窄幅区间内整理，
   振幅 < MAX_BOX_RANGE_PCT（默认 15%）。
2. 至少 MIN_BOX_DAYS 天的收盘价位于箱体范围内（排除零散突刺）。
3. 当日收盘首次突破箱体上沿（前一日仍在上沿之下，避免连续追涨）。
4. 当日成交量 > VOLUME_MULTIPLIER × 20 日均量（放量突破）。
止损：跌破箱体中轨（(box_top + box_bottom) / 2）时退出。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.indicators import calculate_box_range, calculate_volume_ma
from tradeguard.screening.strategies.base import BaseSignalStrategy

# ── 策略超参数 ────────────────────────────────────────────────────────────────
BOX_PERIOD = 20  # 箱体回看天数
MAX_BOX_RANGE_PCT = 0.15  # 箱体最大振幅（15%）
MIN_BOX_DAYS = 10  # 最少有效整理天数（至少一半 bars 在箱内）
VOLUME_MULTIPLIER = 1.5  # 突破当日量能要求（1.5 × MA20）


def box_breakout_screen(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    result_date: str,
    industry: str = "未知",
) -> Optional[Dict]:
    """
    Pure screening function — no DB ops, no side effects.

    Returns a result dict if the stock satisfies the box-breakout entry conditions,
    otherwise returns None.
    """
    min_required = BOX_PERIOD + 21  # need enough history for box + volume_ma20
    if df is None or df.empty or len(df) < min_required:
        return None

    if "box_top" not in df.columns:
        df = calculate_box_range(df, period=BOX_PERIOD)
    if "volume_ma20" not in df.columns:
        df = calculate_volume_ma(df)

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    # Guard: required indicator values must exist
    required = [
        latest.get("close"),
        latest.get("box_top"),
        latest.get("box_bottom"),
        latest.get("box_mid"),
        latest.get("box_range_pct"),
        latest.get("volume"),
        latest.get("volume_ma20"),
        previous.get("close"),
        previous.get("box_top"),
    ]
    if any(pd.isna(v) for v in required):
        return None

    # Condition 1: Box is tight (range < MAX_BOX_RANGE_PCT)
    if latest["box_range_pct"] >= MAX_BOX_RANGE_PCT:
        return None

    # Condition 2: Enough bars actually stayed inside the box during consolidation
    box_window = df.iloc[-(BOX_PERIOD + 1) : -1]  # the BOX_PERIOD bars used  box definition
    box_top_val = float(latest["box_top"])
    box_bottom_val = float(latest["box_bottom"])
    bars_inside = (
        (box_window["close"] <= box_top_val) & (box_window["close"] >= box_bottom_val)
    ).sum()
    if bars_inside < MIN_BOX_DAYS:
        return None

    # Condition 3: Today breaks above the box top for the first time
    if not (latest["close"] > latest["box_top"] and previous["close"] <= previous["box_top"]):
        return None

    # Condition 4: Volume confirmation
    if latest["volume"] <= VOLUME_MULTIPLIER * latest["volume_ma20"]:
        return None

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "latest_price": float(latest["close"]),
        "metadata": {
            "box_top": float(latest["box_top"]),
            "box_bottom": float(latest["box_bottom"]),
            "box_mid": float(latest["box_mid"]),
            "box_range_pct": round(float(latest["box_range_pct"]), 4),
            "box_period": BOX_PERIOD,
            "bars_inside_box": int(bars_inside),
            "volume": float(latest["volume"]),
            "volume_ma20": float(latest["volume_ma20"]),
            "volume_ratio": round(float(latest["volume"]) / float(latest["volume_ma20"]), 2),
        },
    }


class BoxBreakoutStrategy(BaseSignalStrategy):
    name = "box_breakout"
    title = "箱体突破"
    description = (
        f"横盘整理 {BOX_PERIOD} 日后收盘首次放量突破箱体上沿，"
        f"箱体振幅 < {int(MAX_BOX_RANGE_PCT * 100)}%，量能 > {VOLUME_MULTIPLIER}×MA20。"
    )
    required_days = 120
    min_history = BOX_PERIOD + 21

    # Backtest parameters
    stoploss = -0.08
    take_profit = 0.15
    max_holding_days = 15

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        return box_breakout_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = calculate_box_range(df, period=BOX_PERIOD)
        df = calculate_volume_ma(df)
        return df

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Vectorized entry: close breaks above box_top + volume confirmation."""
        if "box_top" not in df.columns:
            df = self.populate_indicators(df)
        close = df["close"]
        breakout = (close.shift(1) <= df["box_top"].shift(1)) & (close > df["box_top"])
        volume_ok = df["volume"] > VOLUME_MULTIPLIER * df["volume_ma20"]
        tight_box = df["box_range_pct"] < MAX_BOX_RANGE_PCT
        return (breakout & volume_ok & tight_box).fillna(False)

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Exit when close falls below box midline (user-specified stop)."""
        if "box_mid" not in df.columns:
            df = self.populate_indicators(df)
        close = df["close"]
        return ((close.shift(1) >= df["box_mid"].shift(1)) & (close < df["box_mid"])).fillna(False)


STRATEGY = BoxBreakoutStrategy()
