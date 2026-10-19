from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from tradeguard.market.schemas import currency_for, normalize_symbol
from tradeguard.portfolio.schemas import StrictModel


class Rules(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    single_stock_limit: Decimal = Field(gt=0, le=1)
    max_trade_loss: Decimal = Field(gt=0, le=1)
    monthly_drawdown_limit: Decimal = Field(gt=0, le=1)
    snapshot_max_age_minutes: int = Field(gt=0, le=10080)
    allow_manual_stop_confirmation: bool = False


class Intent(StrictModel):
    account_id: str
    symbol: str
    currency: Literal["CNY", "USD", "HKD"]
    action: Literal["buy", "add"]
    style: Literal["trend", "value"]
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    stop_evidence: Literal["planned", "manually_confirmed"] = "planned"
    fees: Decimal = Field(default=Decimal(0), ge=0)
    thesis: str = Field(min_length=1)
    _symbol = field_validator("symbol")(normalize_symbol)

    @model_validator(mode="after")
    def check_currency(self) -> Self:
        if self.currency != currency_for(self.symbol):
            raise ValueError("Intent currency does not match exchange")
        if self.stop_price is not None and self.stop_price >= self.price:
            raise ValueError("A long-position stop must be below entry price")
        return self
