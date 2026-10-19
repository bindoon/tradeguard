from tradeguard.screening.strategies.bollinger_breakout import (
    STRATEGY as BOLLINGER_BREAKOUT_STRATEGY,
)
from tradeguard.screening.strategies.box_breakout import STRATEGY as BOX_BREAKOUT_STRATEGY
from tradeguard.screening.strategies.ma_golden_cross import STRATEGY as MA_GOLDEN_CROSS_STRATEGY
from tradeguard.screening.strategies.macd_golden_cross import STRATEGY as MACD_GOLDEN_CROSS_STRATEGY
from tradeguard.screening.strategies.rsi_rebound import STRATEGY as RSI_REBOUND_STRATEGY
from tradeguard.screening.strategies.two_bullish_one_bearish import (
    STRATEGY as TWO_BULLISH_ONE_BEARISH_STRATEGY,
)

REGISTERED_STRATEGIES = [
    MA_GOLDEN_CROSS_STRATEGY,
    TWO_BULLISH_ONE_BEARISH_STRATEGY,
    MACD_GOLDEN_CROSS_STRATEGY,
    RSI_REBOUND_STRATEGY,
    BOLLINGER_BREAKOUT_STRATEGY,
    BOX_BREAKOUT_STRATEGY,
]


STRATEGY_REGISTRY = {strategy.name: strategy for strategy in REGISTERED_STRATEGIES}


def get_registered_strategies(selected_names=None):
    if not selected_names:
        return REGISTERED_STRATEGIES

    missing = [name for name in selected_names if name not in STRATEGY_REGISTRY]
    if missing:
        raise ValueError(f"未知策略: {', '.join(missing)}")

    return [STRATEGY_REGISTRY[name] for name in selected_names]


def get_strategy_summaries():
    return [
        {
            "name": strategy.name,
            "title": strategy.title,
            "description": strategy.description,
        }
        for strategy in REGISTERED_STRATEGIES
    ]
