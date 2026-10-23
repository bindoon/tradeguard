from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from tradeguard.market.schemas import normalize_symbol
from tradeguard.portfolio.schemas import StrictModel


class Scope(StrictModel):
    market: Literal["CN", "US", "HK"]
    source: str = Field(min_length=1, max_length=40)
    adjustment: Literal["forward", "none", "backward"] = "forward"


class WatchInput(Scope):
    symbol: str
    reason: str = Field(default="", max_length=4000)
    scan_run_id: str | None = None
    _symbol = field_validator("symbol")(normalize_symbol)


class AlertInput(Scope):
    symbol: str
    condition: Literal["above", "below"]
    target_price: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    _symbol = field_validator("symbol")(normalize_symbol)
