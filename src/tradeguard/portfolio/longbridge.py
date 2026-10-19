"""Read-only account collector. No order mutation methods are exposed."""

import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from tradeguard.config import settings
from tradeguard.db.models import now
from tradeguard.market.schemas import currency_for, normalize_symbol
from tradeguard.portfolio.schemas import SnapshotInput
from tradeguard.portfolio.service import latest, save_snapshot


class BrokerReader(Protocol):
    def stock_positions(self) -> Any: ...
    def fund_positions(self) -> Any: ...
    def account_balance(self, currency: str) -> list[Any]: ...
    def today_orders(self) -> list[Any]: ...
    def history_orders(self, *, start_at: datetime, end_at: datetime) -> list[Any]: ...


class QuoteReader(Protocol):
    def quote(self, symbols: list[str]) -> list[Any]: ...


def collect(
    trade: BrokerReader,
    quote: QuoteReader,
    account_id: str,
    base_currency: str,
    asset_scope: str = "all",
) -> SnapshotInput:
    # Complete every remote read and validation before changing the current local snapshot.
    positions_response = trade.stock_positions()
    funds_response = trade.fund_positions()
    if asset_scope not in {"all", "stock", "other"}:
        raise ValueError("asset_scope must be all, stock or other")
    balances = trade.account_balance(currency=base_currency)
    if len(balances) != 1:
        raise ValueError("Expected exactly one base-currency balance")
    balance = balances[0]
    if str(balance.currency) != base_currency:
        raise ValueError("Balance currency mismatch")
    raw_positions = [
        p
        for channel in positions_response.channels
        for p in channel.positions
        if Decimal(str(p.quantity)) != 0 and asset_scope != "other"
    ]
    quotes = quote.quote([p.symbol for p in raw_positions]) if raw_positions else []
    prices = {normalize_symbol(q.symbol): Decimal(str(q.last_done)) for q in quotes}
    positions = []
    for p in raw_positions:
        symbol = normalize_symbol(p.symbol)
        if symbol not in prices or prices[symbol] <= 0:
            raise ValueError("Missing positive quote; cannot produce a complete snapshot")
        currency = str(p.currency)
        if currency != currency_for(symbol):
            raise ValueError("Broker position currency mismatch")
        positions.append(
            {
                "symbol": symbol,
                "name": getattr(p, "symbol_name", None),
                "currency": currency,
                "quantity": str(p.quantity),
                "market_value": str(Decimal(str(p.quantity)) * prices[symbol]),
                "average_cost": str(p.cost_price) if p.cost_price else None,
            }
        )

    if asset_scope != "stock":
        for channel in funds_response.channels:
            for fund in channel.positions:
                units = Decimal(str(fund.holding_units))
                nav = Decimal(str(fund.current_net_asset_value))
                cost = Decimal(str(fund.cost_net_asset_value))
                if units == 0:
                    if nav != 0:
                        raise ValueError(
                            "Fund has a NAV but no holding units; cannot value holding"
                        )
                    continue
                positions.append(
                    {
                        "symbol": str(fund.symbol),
                        "name": fund.symbol_name,
                        "instrument_kind": "other",
                        "currency": str(fund.currency),
                        "quantity": str(units),
                        "market_value": str(units * nav) if nav > 0 else None,
                        "average_cost": str(cost) if cost > 0 else None,
                        "observed_at": fund.net_asset_value_day if nav > 0 else None,
                    }
                )

    # Today's orders alone omit older GTC orders. Query both; failures propagate.
    today = now()
    raw_orders = list(trade.today_orders()) + list(
        trade.history_orders(
            start_at=today - timedelta(days=90),
            end_at=today,
        )
    )
    orders = []
    seen = set()
    pending_buys = False

    def positive(value):
        if value is None:
            return None
        value = Decimal(str(value))
        return str(value) if value > 0 else None

    for o in raw_orders:
        oid = str(o.order_id)
        if oid in seen:
            continue
        seen.add(oid)
        raw_type = str(o.order_type).split(".")[-1]
        side = str(o.side).split(".")[-1]
        raw_status = str(o.status).split(".")[-1]
        remaining = Decimal(str(o.quantity)) - Decimal(str(o.executed_quantity))
        active = raw_status in {"New", "PartialFilled"}
        if side == "Buy" and raw_status in {"New", "PartialFilled", "WaitToNew", "WaitToReplace"}:
            pending_buys = True
        kind = (
            "conditional"
            if raw_type in {"LIT", "MIT"}
            else "trailing"
            if raw_type in {"TSLPAMT", "TSLPPCT", "TSMAMT", "TSMPCT"}
            else "market"
            if raw_type in {"MO", "AO"}
            else "limit"
            if raw_type in {"LO", "ELO", "ALO", "ODD", "SLO"}
            else "other"
        )
        status = (
            "active"
            if active
            else "cancelled"
            if raw_status in {"Canceled", "Rejected"}
            else "expired"
            if raw_status == "Expired"
            else "pending"
        )
        if remaining > 0:
            orders.append(
                {
                    "symbol": normalize_symbol(o.symbol),
                    "quantity": str(remaining),
                    "order_kind": kind,
                    "side": "sell" if side == "Sell" else "buy",
                    "trigger_price": positive(getattr(o, "trigger_price", None)),
                    "limit_price": positive(getattr(o, "price", None)),
                    "trailing_percent": positive(getattr(o, "trailing_percent", None)),
                    "status": status,
                    "evidence": "broker_verified",
                    "broker_order_id": oid,
                    "raw_type": raw_type,
                    "observed_at": today,
                    "note": "Standalone touched orders do not identify stop-loss vs take-profit intent."
                    if kind == "conditional"
                    else None,
                }
            )
        for attached in getattr(o, "attached_orders", []):
            aid = str(attached.order_id)
            if aid in seen:
                continue
            seen.add(aid)
            q = Decimal(str(attached.quantity)) - Decimal(str(attached.executed_qty))
            if q <= 0:
                continue
            attached_type = str(attached.attached_type_display).split(".")[-1].lower()
            attached_kind = (
                "stop_loss"
                if attached_type in {"stoploss", "stop_loss", "2"}
                else "take_profit"
                if attached_type in {"profittaker", "profit_taker", "1"}
                else "conditional"
            )
            trigger_state = str(getattr(attached, "trigger_status", "Unknown")).split(".")[-1]
            orders.append(
                {
                    "symbol": normalize_symbol(o.symbol),
                    "quantity": str(q),
                    "order_kind": attached_kind,
                    "side": "sell" if side == "Buy" else "buy",
                    "trigger_price": positive(attached.trigger_price),
                    "limit_price": positive(getattr(attached, "submit_price", None)),
                    "status": "cancelled"
                    if attached.withdrawn
                    else "active"
                    if trigger_state == "Active"
                    else "pending",
                    "evidence": "broker_verified",
                    "broker_order_id": aid,
                    "raw_type": "attached:" + attached_type,
                    "observed_at": today,
                }
            )
    # Use available base-currency cash, not buying power or margin capacity.
    cash = sum(
        (
            Decimal(str(c.available_cash))
            for c in balance.cash_infos
            if str(c.currency) == base_currency
        ),
        Decimal(0),
    )
    initial_margin = Decimal(str(balance.init_margin))
    negative_cash = any(Decimal(str(c.available_cash)) < 0 for c in balance.cash_infos)
    return SnapshotInput.model_validate(
        {
            "account_id": account_id,
            "broker": "longbridge",
            "label": account_id,
            "external_id": str(uuid4()),
            "as_of": today,
            "base_currency": base_currency,
            "net_assets": str(balance.net_assets) if asset_scope == "all" else None,
            "cash": str(cash) if asset_scope == "all" else None,
            "margin_used": initial_margin > 0 or negative_cash,
            "pending_buy_orders": pending_buys,
            "monthly_drawdown": None,
            "record_origin": "broker_api",
            "asset_scope": asset_scope,
            "positions": positions,
            "orders": orders if asset_scope != "other" else [],
        }
    )


def sync(account_id: str, base_currency: str) -> dict:
    if base_currency not in {"CNY", "HKD", "USD"}:
        raise ValueError("base_currency must be CNY, HKD or USD")
    cfg = settings()
    credentials = (cfg.longbridge_app_key, cfg.longbridge_app_secret, cfg.longbridge_access_token)
    if any(c is None for c in credentials):
        raise ValueError("Configure TRADEGUARD_LONGBRIDGE_APP_KEY, APP_SECRET and ACCESS_TOKEN")
    try:
        os.environ["LONGBRIDGE_REGION"] = cfg.longbridge_region
        from longbridge.openapi import Config, QuoteContext, TradeContext
    except ImportError as exc:
        raise ValueError("Install the SDK: uv sync --extra longbridge") from exc
    try:
        key, secret, token = credentials
        assert key is not None and secret is not None and token is not None
        config = Config.from_apikey(
            key.get_secret_value(), secret.get_secret_value(), token.get_secret_value()
        )
        previous = latest(account_id)
        scope = previous.payload.get("asset_scope", "all") if previous else "all"
        snapshot = collect(
            TradeContext(config), QuoteContext(config), account_id, base_currency, scope
        )
    except ValueError:
        raise
    except Exception as exc:
        code = re.search(r"\bcode=(\d+)", str(exc))
        if code and code.group(1) == "401003":
            raise RuntimeError(
                "Longbridge token expired (401003); renew the configured access token"
            ) from None
        raise RuntimeError(
            f"Longbridge snapshot failed ({type(exc).__name__}); nothing saved"
        ) from None
    return {
        **save_snapshot(snapshot, broker_verified=True),
        "warnings": [
            "Monthly drawdown and cross-currency FX require additional evidence; "
            "only 90 days of historical orders queried."
        ],
    }
