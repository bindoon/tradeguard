"""
Technical indicators calculation module.
"""

import numpy as np


def calculate_moving_averages(df):
    """
    Calculate moving averages for closing prices.

    Args:
        df: DataFrame with 'close' column

    Returns:
        pd.DataFrame: Original df with added MA columns
    """
    df = df.copy()
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma10"] = df["close"].rolling(window=10).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()
    df["ma60"] = df["close"].rolling(window=60).mean()
    return df


def calculate_ema(df, periods=(12, 26)):
    """
    Calculate exponential moving averages for closing prices.

    Args:
        df: DataFrame with 'close' column
        periods: Tuple of EMA periods to calculate

    Returns:
        pd.DataFrame: Original df with added EMA columns
    """
    df = df.copy()
    for period in periods:
        df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD indicator.

    Args:
        df: DataFrame with 'close' column
        fast: Fast EMA period
        slow: Slow EMA period
        signal: Signal EMA period

    Returns:
        pd.DataFrame: Original df with MACD columns
    """
    df = calculate_ema(df, periods=(fast, slow))
    df["macd"] = df[f"ema{fast}"] - df[f"ema{slow}"]  # 趋势强度
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()  # 趋势变化速率
    df["macd_hist"] = df["macd"] - df["macd_signal"]  # 买卖压力
    return df


def calculate_rsi(df, period=14):
    """
    Calculate RSI indicator.

    Args:
        df: DataFrame with 'close' column
        period: RSI lookback period

    Returns:
        pd.DataFrame: Original df with 'rsi' column
    """
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(100)
    return df


def calculate_bollinger_bands(df, window=20, num_std=2):
    """
    Calculate Bollinger Bands.

    Args:
        df: DataFrame with 'close' column
        window: Rolling window length
        num_std: Number of standard deviations

    Returns:
        pd.DataFrame: Original df with Bollinger Band columns
    """
    df = df.copy()
    rolling_mean = df["close"].rolling(window=window).mean()
    rolling_std = df["close"].rolling(window=window).std()
    df["bb_middle"] = rolling_mean
    df["bb_upper"] = rolling_mean + (rolling_std * num_std)
    df["bb_lower"] = rolling_mean - (rolling_std * num_std)
    return df


def calculate_volume_ma(df):
    """
    Calculate moving average for volume.

    Args:
        df: DataFrame with 'volume' column

    Returns:
        pd.DataFrame: Original df with added volume MA column
    """
    df = df.copy()
    df["volume_ma20"] = df["volume"].rolling(window=20).mean()
    return df


def calculate_daily_returns(df):
    """
    Calculate daily percentage returns.

    Args:
        df: DataFrame with 'close' column

    Returns:
        pd.DataFrame: Original df with added 'return' column
    """
    df = df.copy()
    df["return"] = df["close"].pct_change()
    return df


def detect_consecutive_gains(df, days=3):
    """
    Detect if stock has consecutive rising prices with increasing gains.

    Args:
        df: DataFrame with 'close' and 'return' columns
        days: Number of consecutive days to check (default: 3)

    Returns:
        bool: True if pattern detected
    """
    if len(df) < days:
        return False

    # Get last N days
    recent = df.tail(days)

    # Check if prices are rising
    closes = recent["close"].values
    prices_rising = all(closes[i] > closes[i - 1] for i in range(1, len(closes)))

    # Check if gains are increasing
    returns = recent["return"].dropna().values
    if len(returns) < days - 1:
        return False
    gains_increasing = all(returns[i] > returns[i - 1] for i in range(1, len(returns)))

    return prices_rising and gains_increasing


def calculate_box_range(df, period=20):
    """
    Calculate rolling box (consolidation range) boundaries using close prices.

    For each row, looks back `period` bars (excluding current bar) to compute:
      - box_top    : max close over the lookback window
      - box_bottom : min close over the lookback window
      - box_mid    : (box_top + box_bottom) / 2
      - box_range_pct : (box_top - box_bottom) / box_bottom

    Args:
        df: DataFrame with 'close' column
        period: Lookback window in trading days (default: 20)

    Returns:
        pd.DataFrame: Original df with added box_top, box_bottom, box_mid, box_range_pct columns
    """
    df = df.copy()
    # shift(1) so today's close is NOT included in the box definition
    df["box_top"] = df["close"].shift(1).rolling(window=period).max()
    df["box_bottom"] = df["close"].shift(1).rolling(window=period).min()
    df["box_mid"] = (df["box_top"] + df["box_bottom"]) / 2
    df["box_range_pct"] = (df["box_top"] - df["box_bottom"]) / df["box_bottom"]
    return df


def detect_cycle_low(df, period=60):
    """
    Detect if stock reached a cycle low within the period.

    Args:
        df: DataFrame with 'low' column
        period: Period to check for cycle low (default: 60)

    Returns:
        bool: True if at cycle low
    """
    if len(df) < period:
        return False

    # Get the minimum low over the period
    min_low = df["low"].tail(period).min()

    # Check if recent low equals the minimum
    recent_low = df["low"].iloc[-1]

    return recent_low == min_low
