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
        """Causal adapter over screen(); never maintain a second entry definition.

        Missing warmup/dependency evidence is pandas.NA, not a negative signal.
        """
        from tradeguard.backtesting.plugins import signal_at
        from tradeguard.screening.strategies.registry import STRATEGY_REGISTRY

        strategies = {**STRATEGY_REGISTRY, self.name: self}
        values = []
        for end in range(1, len(df) + 1):
            frame = df.iloc[:end].tail(400).copy()
            if "date" not in frame:
                frame["date"] = frame.index.astype(str)
            found = signal_at(self, frame, "", "", strategies)
            values.append(found["hit"] if found is not None else pd.NA)
        return pd.Series(values, index=df.index, dtype="boolean")

    def exit_signal(self, df: pd.DataFrame) -> pd.Series:
        """Return boolean Series: True on rows where signal-based exit is triggered.
        Default: no signal exit (rely on stoploss/take_profit/max_holding_days)."""
        return pd.Series(False, index=df.index)
