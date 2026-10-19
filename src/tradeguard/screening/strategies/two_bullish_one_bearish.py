"""
两阳夹一阴策略（纯函数版本）

策略描述:
找在 ma_golden_cross（均线金叉）发生后的2-4天内出现"两阳夹一阴"形态的股票。

定义:
- 阳线: 收盘价 > 开盘价 (close > open)
- 阴线: 收盘价 < 开盘价 (close < open)
- 两阳夹一阴: 连续三天，第一天阳线，第二天阴线，第三天阳线

检测逻辑:
1. 获取过去4天内被 ma_golden_cross 策略筛选出的股票（记录金叉日期）
2. 对每只股票，从金叉日往后数，检查金叉后第2、3、4天是否形成"两阳夹一阴"
3. 形态位置：[金叉+2天(阳), 金叉+3天(阴), 金叉+4天(阳)]

示例：
- 假设某股票在 2月1日 发生金叉
- 检查 2月3日(阳)、2月4日(阴)、2月5日(阳) 是否形成形态
- 如果符合，则该股票符合筛选条件

注意：此策略模块只负责计算和返回结果，不进行数据库操作。
数据库操作应该由调用方（如 run_scan.py 或 API 层）处理。
"""

from typing import Dict, Optional

import pandas as pd

from tradeguard.screening.strategies.base import BaseSignalStrategy, StrategyDependency


def is_bullish_candle(row) -> bool:
    """
    判断是否为阳线

    Args:
        row: DataFrame的一行数据，包含 open 和 close

    Returns:
        bool: 是否为阳线
    """
    if pd.isna(row["open"]) or pd.isna(row["close"]):
        return False
    return row["close"] > row["open"]


def is_bearish_candle(row) -> bool:
    """
    判断是否为阴线

    Args:
        row: DataFrame的一行数据，包含 open 和 close

    Returns:
        bool: 是否为阴线
    """
    if pd.isna(row["open"]) or pd.isna(row["close"]):
        return False
    return row["close"] < row["open"]


def detect_two_bullish_one_bearish_after_date(
    df: pd.DataFrame, golden_cross_date: str
) -> Optional[int]:
    """
    检测从金叉日往后2-4天内是否出现"两阳夹一阴"形态

    逻辑：
    - 找到金叉日在数据中的位置
    - 从金叉日往后数，检查后续2-4天内是否出现该形态
    - 形态需要连续3天：阳线 -> 阴线 -> 阳线

    可能的形态位置：
    - 金叉后第2、3、4天：[金叉+2, 金叉+3, 金叉+4]

    Args:
        df: 股票数据DataFrame（需要包含 'date' 列）
        golden_cross_date: 金叉发生的日期（格式：YYYY-MM-DD）

    Returns:
        int or None: 如果出现形态，返回形态最后一天相对于金叉日的天数（2-4），否则返回 None
    """
    if df is None or df.empty:
        return None

    # 确保 date 列存在且为字符串格式
    if "date" not in df.columns:
        return None

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # 找到金叉日在数据中的索引
    golden_cross_idx = None
    for idx, row in df.iterrows():
        if row["date"] == golden_cross_date:
            golden_cross_idx = idx
            break

    if golden_cross_idx is None:
        return None

    # 检查金叉后第2、3、4天是否形成"两阳夹一阴"
    # 形态需要连续3天，所以检查位置为：[金叉+2, 金叉+3, 金叉+4]
    try:
        # 金叉后第2天是第一根阳线，第3天是阴线，第4天是第二根阳线
        day1_idx = golden_cross_idx + 2  # 金叉后第2天（第一根阳线）
        day2_idx = golden_cross_idx + 3  # 金叉后第3天（阴线）
        day3_idx = golden_cross_idx + 4  # 金叉后第4天（第二根阳线）

        # 确保索引不越界
        if day3_idx >= len(df):
            return None

        day1 = df.iloc[day1_idx]
        day2 = df.iloc[day2_idx]
        day3 = df.iloc[day3_idx]

        # 检查形态: 阳线 -> 阴线 -> 阳线
        if is_bullish_candle(day1) and is_bearish_candle(day2) and is_bullish_candle(day3):
            return 4  # 形态最后一天是金叉后第4天

    except (IndexError, KeyError):
        pass

    return None


def two_bullish_one_bearish_screen(
    stock_code: str,
    stock_name: str,
    df: pd.DataFrame,
    result_date: str,
    industry: str = "未知",
    ma_golden_cross_date: str = None,
) -> Optional[Dict]:
    """
    两阳夹一阴策略筛选（纯函数版本）

    检测股票在金叉后2-4天是否出现"两阳夹一阴"形态

    Args:
        stock_code: 股票代码
        stock_name: 股票名称
        df: 股票数据DataFrame（必须包含 'date' 列）
        result_date: 分析的数据日期
        industry: 所属行业
        ma_golden_cross_date: 该股票发生金叉的日期（必需）

    Returns:
        dict: 如果符合条件返回结果字典，否则返回 None
              返回格式: {
                  'stock_code': str,
                  'stock_name': str,
                  'result_date': str,
                  'industry': str,
                  'pattern_day': int,  # 形态最后一天相对于金叉日的天数（2-4）
                  'metadata': dict  # 包含 ma_golden_cross_date 等信息
              }
    """
    # 数据校验
    if df is None or df.empty or len(df) < 10:
        return None

    if not ma_golden_cross_date:
        return None

    # 检测金叉后2-4天是否出现形态
    pattern_day = detect_two_bullish_one_bearish_after_date(df, ma_golden_cross_date)

    # 如果没有找到形态，返回 None
    if pattern_day is None:
        return None

    # 获取最新数据
    latest = df.iloc[-1]

    # 返回结果
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "result_date": result_date,
        "industry": industry,
        "pattern_day": pattern_day,
        "latest_price": float(latest["close"]),
        "metadata": {
            "pattern_day": pattern_day,
            "ma_golden_cross_date": ma_golden_cross_date,
            "latest_volume": float(latest.get("volume", 0)),
        },
    }


class TwoBullishOneBearishStrategy(BaseSignalStrategy):
    name = "two_bullish_one_bearish"
    title = "两阳夹一阴"
    description = "基于均线金叉结果，检查金叉后第 2 至第 4 天是否出现两阳夹一阴。"
    required_days = 120
    min_history = 10
    dependency = StrategyDependency(strategy_name="ma_golden_cross", days_ago=4)
    max_holding_days = 10  # short-term pattern, exit sooner

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict] = None,
    ) -> Optional[Dict]:
        ma_golden_cross_date = None
        if dependency_result:
            ma_golden_cross_date = dependency_result.get("target_date")

        return two_bullish_one_bearish_screen(
            stock_code=stock_code,
            stock_name=stock_name,
            df=df,
            result_date=result_date,
            industry=industry,
            ma_golden_cross_date=ma_golden_cross_date,
        )

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        from tradeguard.screening.indicators import calculate_moving_averages

        return calculate_moving_averages(df)

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Entry: standalone two-bullish-one-bearish candle pattern (no MA dependency).
        Pattern: day-2 bullish, day-1 bearish, day-0 bullish."""
        bullish = df["close"] > df["open"]
        bearish = df["close"] < df["open"]
        pattern = bullish.shift(2).fillna(False) & bearish.shift(1).fillna(False) & bullish
        return pattern.fillna(False)

    # exit_signal inherits default (all False) – rely on stoploss/take_profit/max_holding_days


STRATEGY = TwoBullishOneBearishStrategy()
