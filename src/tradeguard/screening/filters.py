from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class FilterOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter_st: bool = True
    filter_new_stock: bool = True
    filter_liquidity: bool = True
    filter_suspended: bool = True
    filter_limit: bool = True
    min_avg_amount: float = Field(default=100_000_000, ge=0)
    min_listed_days: int = Field(default=365, ge=0)
    limit_pct: float = Field(default=0.095, gt=0, le=1)

    @classmethod
    def for_market(cls, market: str, overrides: dict | None = None):
        defaults = (
            {}
            if market == "CN"
            else {
                "filter_st": False,
                "filter_limit": False,
                "min_avg_amount": 20_000_000,
                "min_listed_days": 90,
            }
        )
        return cls(**{**defaults, **(overrides or {})})


def rejection(security, bars: list[dict], target: date, market: str, options: FilterOptions):
    if not bars or bars[-1]["trade_date"] != target:
        return "missing_target_bar", []
    if len(bars) < 60:
        return "insufficient_history", []
    name = (security.name or "").upper()
    flagged = bool(getattr(security, "is_st", False)) or "ST" in name
    if options.filter_st and market == "CN" and flagged:
        return "st_stock", []
    if options.filter_suspended and bars[-1]["volume"] <= 0:
        return "suspended_or_zero_volume", []
    warnings = []
    if options.filter_new_stock:
        listed = security.list_date
        # A cached bar proves the security was already listed at that time.
        earliest = listed or bars[0]["trade_date"]
        if (target - earliest).days < options.min_listed_days:
            if listed:
                return "recent_listing", []
            warnings.append("listing_date_unverified")
    if options.filter_liquidity:
        amounts = [
            float(b["amount"]) if b["amount"] is not None else float(b["close"] * b["volume"])
            for b in bars[-5:]
        ]
        if sum(amounts) / len(amounts) < options.min_avg_amount:
            return "low_liquidity", warnings
    if options.filter_limit and market == "CN" and len(bars) > 1:
        code = security.symbol.split(".")[0]
        limit = (
            0.295
            if security.symbol.endswith(".BJ")
            else 0.195
            if code.startswith(("688", "300", "301"))
            else options.limit_pct
        )
        if abs(float(bars[-1]["close"] / bars[-2]["close"] - 1)) >= limit:
            return "limit_move", warnings
    return None, warnings
