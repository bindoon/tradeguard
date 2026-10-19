from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradeguard.market.schemas import currency_for, normalize_symbol


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Position(StrictModel):
    symbol: str
    name: str | None = None
    instrument_kind: Literal["stock", "other"] = "stock"
    currency: Literal["CNY", "USD", "HKD"]
    quantity: Decimal
    market_value: Decimal | None = None
    average_cost: Decimal | None = Field(default=None, gt=0)
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def currency_matches(self) -> Self:
        if self.quantity == 0:
            raise ValueError("Remove zero-quantity positions instead of storing them")
        if self.instrument_kind == "stock":
            self.symbol = normalize_symbol(self.symbol)
        if self.instrument_kind == "stock" and self.currency != currency_for(self.symbol):
            raise ValueError("Position currency does not match exchange")
        return self


class StopOrder(StrictModel):
    symbol: str
    quantity: Decimal | None = Field(default=None, gt=0)
    trigger_price: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    order_kind: Literal[
        "stop_loss", "take_profit", "trailing", "conditional", "limit", "market", "other"
    ] = "stop_loss"
    side: Literal["buy", "sell"] = "sell"
    status: Literal["active", "cancelled", "expired", "pending", "filled", "unknown"]
    evidence: Literal["planned", "manually_confirmed", "broker_verified"]
    broker_order_id: str | None = None
    raw_type: str | None = None
    trailing_percent: Decimal | None = Field(default=None, gt=0)
    activation_price: Decimal | None = Field(default=None, gt=0)
    observed_at: datetime | None = None
    note: str | None = None
    _symbol = field_validator("symbol")(normalize_symbol)


class SnapshotInput(StrictModel):
    account_id: str = Field(min_length=1, max_length=60)
    broker: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=100)
    external_id: str = Field(min_length=1, max_length=100)
    as_of: datetime
    base_currency: Literal["CNY", "USD", "HKD"]
    net_assets: Decimal | None = None
    cash: Decimal | None = None
    margin_used: bool | None = None
    assets_as_of: datetime | None = None
    pending_buy_orders: bool = False
    monthly_drawdown: Decimal | None = Field(default=None, ge=-1, le=0)
    fx_to_base: dict[str, Decimal] = Field(default_factory=dict)
    positions: list[Position]
    orders: list[StopOrder]
    record_origin: Literal["manual", "broker_api", "legacy_broker_cache", "legacy_manual"] = (
        "manual"
    )
    statement: str | None = None
    asset_scope: Literal["all", "stock", "other"] = "all"
    previous_snapshot_id: str | None = None

    @field_validator("as_of")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must have a timezone")
        return value

    @field_validator("fx_to_base")
    @classmethod
    def positive_rates(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if any(not r.is_finite() or r <= 0 for r in value.values()):
            raise ValueError("FX rates must be finite and positive")
        return value

    @model_validator(mode="after")
    def unique_positions(self) -> Self:
        if len({p.symbol for p in self.positions}) != len(self.positions):
            raise ValueError("Aggregate duplicate positions within one account snapshot")
        if self.base_currency in self.fx_to_base and self.fx_to_base[self.base_currency] != 1:
            raise ValueError("Base-currency FX rate must be 1")
        return self


class PositionPatch(StrictModel):
    symbol: str
    quantity: Decimal | None = None
    average_cost: Decimal | None = Field(default=None, gt=0)
    market_value: Decimal | None = None
    name: str | None = None
    _symbol = field_validator("symbol")(normalize_symbol)

    @field_validator("quantity")
    @classmethod
    def explicit_quantity(cls, value):
        if value is None:
            raise ValueError(
                "Quantity cannot be null; omit unchanged quantity or use zero to remove"
            )
        return value


class ManualPatch(StrictModel):
    statement: str = Field(min_length=1, description="The user's actual update statement")
    as_of: datetime
    base_currency: Literal["CNY", "USD", "HKD"] | None = None
    positions: list[PositionPatch] = Field(default_factory=list)
    orders: list[StopOrder] | None = None
    replace_orders: bool = False
    net_assets: Decimal | None = None
    cash: Decimal | None = None
    margin_used: bool | None = None
