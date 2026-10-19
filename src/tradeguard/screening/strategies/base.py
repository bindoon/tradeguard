from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd


@dataclass(frozen=True)
class StrategyDependency:
    strategy_name: str
    days_ago: int


class BaseSignalStrategy:
    name: str = ""
    title: str = ""
    description: str = ""
    required_days: int = 120
    min_history: int = 60
    dependency: Optional[StrategyDependency] = None

    # Backtest parameters
    stoploss: float = -0.08  # -8% stop loss
    take_profit: float = 0.15  # +15% take profit
    max_holding_days: int = 20  # max days before force-exit

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def screen(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        result_date: str,
        industry: str = "未知",
        dependency_result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def metadata(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": self.title,
            "description": self.description,
        }
        if self.dependency:
            payload["dependency"] = {
                "strategy_name": self.dependency.strategy_name,
                "days_ago": self.dependency.days_ago,
            }
        return payload

    def populate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicator columns needed by entry/exit signals.
        Override in subclasses to add strategy-specific indicators."""
        return df

    def entry_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return boolean Series: True on rows where entry condition is met.
        Must override in subclasses to enable backtesting."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement entry_signal()")

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return boolean Series: True on rows where signal-based exit is triggered.
        Default: no signal exit (rely on stoploss/take_profit/max_holding_days)."""
        return pd.Series(False, index=df.index)
