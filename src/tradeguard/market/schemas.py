import re
from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_symbol(value: str) -> str:
    value = value.strip().upper()
    if re.fullmatch(r"(SH|SZ|BJ)\.\d{6}", value):
        exchange, code = value.split(".")
        value = f"{code}.{exchange}"
    if re.fullmatch(r"\d+\.HK", value):
        value = f"{int(value[:-3]):05d}.HK"
    if not re.fullmatch(r"(\d{6}\.(SH|SZ|BJ)|\d{5}\.HK|[A-Z][A-Z0-9.-]*\.US)", value):
        raise ValueError("Symbol must include exchange, e.g. 600519.SH, 00700.HK, AAPL.US")
    return value


def currency_for(symbol: str) -> str:
    return {"HK": "HKD", "US": "USD"}.get(symbol.rsplit(".", 1)[1], "CNY")


class BarInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbol: str
    name: str = ""
    industry: str | None = None
    trade_date: date
    source: str = Field(min_length=1, max_length=40)
    adjustment: Literal["none", "forward", "backward"]
    open: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    high: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    low: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    close: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    volume: Decimal = Field(ge=0, max_digits=30, decimal_places=4)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=30, decimal_places=4)

    _symbol = field_validator("symbol")(normalize_symbol)

    @model_validator(mode="after")
    def prices(self) -> Self:
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC range is inconsistent")
        if self.low > self.high:
            raise ValueError("low exceeds high")
        return self
