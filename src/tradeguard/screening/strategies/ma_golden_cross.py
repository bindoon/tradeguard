"""
均线金叉多头排列策略（纯函数版本）

条件:
1. 两天前5日线上穿10日线（金叉）@laowang
2. 均线多头排列: MA5 > MA10 > MA20 > MA60 @laowang
3. 成交量分析（90日数据）

注意：此策略模块只负责计算和返回结果，不进行数据库操作。
数据库操作应该由调用方（如 run_scan.py 或 API 层）处理。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.indicators import calculate_moving_averages
from tradeguard.screening.strategies.base import BaseSignalStrategy


def detect_ma5_cross_ma10(df, days_ago=2):
    """
    检测5日线上穿10日线（金叉）

    Args:
        df: 包含ma5和ma10的DataFrame
        days_ago: 金叉发生在几天前（默认2天前）

    Returns:
        bool: 是否发生金叉
    """
    if len(df) < days_ago + 2:
        return False

    # 金叉发生的那天
    cross_day_idx = -days_ago - 1
    prev_day_idx = cross_day_idx - 1

    # 金叉条件: 前一天 MA5 <= MA10, 当天 MA5 > MA10
    ma5_prev = df["ma5"].iloc[prev_day_idx]
    ma10_prev = df["ma10"].iloc[prev_day_idx]
    ma5_cross = df["ma5"].iloc[cross_day_idx]
    ma10_cross = df["ma10"].iloc[cross_day_idx]

    # 检查是否有NaN
    if pd.isna(ma5_prev) or pd.isna(ma10_prev) or pd.isna(ma5_cross) or pd.isna(ma10_cross):
        return False

    return ma5_prev <= ma10_prev and ma5_cross > ma10_cross


def check_bullish_alignment(df):
    """
    检测均线多头排列: MA5 > MA10 > MA20 > MA60

    Args:
        df: 包含均线数据的DataFrame

    Returns:
        bool: 是否多头排列
    """
    if len(df) < 1:
        return False

    latest = df.iloc[-1]

    ma5 = latest.get("ma5")
    ma10 = latest.get("ma10")
    ma20 = latest.get("ma20")
    ma60 = latest.get("ma60")

    # 检查是否有NaN
    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20) or pd.isna(ma60):
        return False

    return ma5 > ma10 > ma20 > ma60


def analyze_volume(df, period=90):
    """
    分析成交量情况

    Args:
        df: 包含volume的DataFrame
        period: 分析周期（默认90天）

    Returns:
        dict: 成交量分析结果
    """
    if len(df) < period:
        recent_df = df
    else:
        recent_df = df.tail(period)

    avg_volume = recent_df["volume"].mean()
    latest_volume = df["volume"].iloc[-1]
    max_volume = recent_df["volume"].max()
    min_volume = recent_df["volume"].min()

    # 计算最后一日成交量相对于均值的倍数
    volume_ratio = latest_volume / avg_volume if avg_volume > 0 else 0

    # 计算近5日平均成交量
    recent_5d_avg = df["volume"].tail(5).mean()
    volume_trend = recent_5d_avg / avg_volume if avg_volume > 0 else 0

    return {
        "avg_volume": avg_volume,  # 90日均量
        "latest_volume": latest_volume,  # 当日成交量
        "volume_ratio": volume_ratio,  # 当日成交量/90日均量
        "volume_trend": volume_trend,  # 近5日均量/90日均量
        "max_volume": max_volume,  # 90日最大成交量
        "min_volume": min_volume,  # 90日最小成交量
    }


def build_ma_debug_metadata(df, days_ago=2):
    """构造均线判定的调试信息，便于解释为什么命中。"""
    latest = df.iloc[-1]
    cross_day_idx = -days_ago - 1
    prev_day_idx = cross_day_idx - 1
    cross_day = df.iloc[cross_day_idx]
    prev_day = df.iloc[prev_day_idx]

    return {
        "latest": {
            "date": str(latest.get("date")) if "date" in latest else None,
            "close": float(latest["close"]),
            "ma5": float(latest["ma5"]),
            "ma10": float(latest["ma10"]),
            "ma20": float(latest["ma20"]),
            "ma60": float(latest["ma60"]),
        },
        "cross_check": {
            "days_ago": days_ago,
            "prev_date": str(prev_day.get("date")) if "date" in prev_day else None,
            "cross_date": str(cross_day.get("date")) if "date" in cross_day else None,
            "prev_ma5": float(prev_day["ma5"]),
            "prev_ma10": float(prev_day["ma10"]),
            "prev_ma20": float(prev_day["ma20"]),
            "cross_ma5": float(cross_day["ma5"]),
            "cross_ma10": float(cross_day["ma10"]),
            "cross_ma20": float(cross_day["ma20"]),
            "crossed": bool(
                prev_day["ma5"] <= prev_day["ma10"] and cross_day["ma5"] > cross_day["ma10"]
            ),
        },
    }


def ma_golden_cross_screen(
    stock_code: str, stock_name: str, df: pd.DataFrame, result_date: str, industry: str = "未知"
) -> Optional[Dict]:
    """
    均线金叉多头排列策略筛选（纯函数版本）

    这是一个纯函数，只负责计算是否符合策略条件并返回结果。
    不进行任何数据库读写操作。

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        df: 股票数据DataFrame（至少120天，应该已经包含均线数据）
        result_date: 分析的数据日期
        industry: 所属行业

    Returns:
        dict: 如果符合条件返回结果字典，否则返回 None
              返回格式: {
                  'stock_code': str,
                  'stock_name': str,
                  'result_date': str,
                  'industry': str,
                  'volume_ratio': float,
                  'volume_trend': float,
                  'latest_price': float,
                  'metadata': dict  # 包含 ma5, ma10, ma20, ma60 等
              }
    """
    # 数据校验
    if df is None or df.empty or len(df) < 60:
        return None

    # 如果df还没有计算均线，则计算
    if "ma5" not in df.columns:
        df = calculate_moving_averages(df)

    # 检测两天前的金叉
    ma5_cross_ma10 = detect_ma5_cross_ma10(df, days_ago=2)
    if not ma5_cross_ma10:
        return None

    # 检测多头排列
    bullish_alignment = check_bullish_alignment(df)
    if not bullish_alignment:
        return None

    # 成交量分析
    volume_analysis = analyze_volume(df, period=90)
    ma_debug = build_ma_debug_metadata(df, days_ago=2)

    # 获取最新数据
    latest = df.iloc[-1]

    # 返回结果（只在符合策略时返回）
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "volume_ratio": volume_analysis["volume_ratio"],
        "volume_trend": volume_analysis["volume_trend"],
        "latest_price": float(latest["close"]),
        "metadata": {
            "avg_volume": float(volume_analysis["avg_volume"]),
            "volume_ratio": float(volume_analysis["volume_ratio"]),
            "volume_trend": float(volume_analysis["volume_trend"]),
            "ma_debug": ma_debug,
        },
    }


# 注意：以下函数已移除，数据库操作应由扫描调度层处理
# - run_strategy()
# - main()
#
# 如需验证此策略，请通过测试或 `run_scan.py` 调度执行


class MaGoldenCrossStrategy(BaseSignalStrategy):
    name = "ma_golden_cross"
    title = "均线金叉多头排列"
    description = "两天前 5 日线上穿 10 日线，且当前均线保持多头排列。"
    required_days = 120
    min_history = 60

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        return ma_golden_cross_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return calculate_moving_averages(df)

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Entry: MA5 crosses above MA10 + bullish alignment (MA5>MA10>MA20>MA60)."""
        if "ma5" not in df.columns:
            df = self.populate_indicators(df)
        ma5 = df["ma5"]
        ma10 = df["ma10"]
        ma20 = df["ma20"]
        ma60 = df["ma60"]
        cross = (ma5.shift(1) <= ma10.shift(1)) & (ma5 > ma10)
        aligned = (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)
        return (cross & aligned).fillna(False)

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Exit: MA5 death-crosses below MA10."""
        if "ma5" not in df.columns:
            df = self.populate_indicators(df)
        ma5 = df["ma5"]
        ma10 = df["ma10"]
        return ((ma5.shift(1) >= ma10.shift(1)) & (ma5 < ma10)).fillna(False)


STRATEGY = MaGoldenCrossStrategy()
