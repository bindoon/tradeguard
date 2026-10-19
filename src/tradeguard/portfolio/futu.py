"""Optional Futu collector; reads account data through an already authenticated OpenD."""

import contextlib
import socket
import sys
from decimal import Decimal
from uuid import uuid4

from tradeguard.config import settings
from tradeguard.db.models import now
from tradeguard.market.schemas import currency_for, normalize_symbol
from tradeguard.portfolio.schemas import SnapshotInput
from tradeguard.portfolio.service import save_snapshot


def number(value) -> Decimal:
    try:
        n = Decimal(str(value))
    except ArithmeticError as e:
        raise ValueError("Futu returned a missing numeric field") from e
    if not n.is_finite():
        raise ValueError("Futu returned a non-finite numeric field")
    return n


def normalize_snapshot(
    account_id: str, base_currency: str, balance: dict, positions: list[dict], orders: list[dict]
) -> SnapshotInput:
    normalized = []
    for p in positions:
        quantity = number(p["qty"])
        if quantity == 0:
            continue
        market, ticker = p["code"].split(".", 1)
        symbol = normalize_symbol(f"{ticker}.{market}")
        expected = currency_for(symbol)
        if p.get("currency") and p["currency"] != expected:
            raise ValueError("Futu currency mismatch")
        normalized.append(
            {
                "symbol": symbol,
                "currency": expected,
                "quantity": str(quantity),
                "market_value": str(number(p["market_val"])),
                "average_cost": str(number(p["cost_price"])) if p.get("cost_price_valid") else None,
            }
        )
    stops = []
    observed = now()

    def positive(value):
        if value is None:
            return None
        n = number(value)
        return str(n) if n > 0 else None

    pending_buys = False
    for order in orders:
        if order["order_status"] not in {"SUBMITTED", "FILLED_PART"}:
            continue
        if order["trd_side"] == "BUY":
            pending_buys = True
        remaining = number(order["qty"]) - number(order["dealt_qty"])
        if remaining <= 0:
            continue
        market, ticker = order["code"].split(".", 1)
        raw_type = order["order_type"]
        kind = (
            "stop_loss"
            if raw_type in {"STOP", "STOP_LIMIT"}
            else "take_profit"
            if raw_type in {"MARKET_IF_TOUCHED", "LIMIT_IF_TOUCHED"}
            else "trailing"
            if raw_type in {"TRAILING_STOP", "TRAILING_STOP_LIMIT"}
            else "market"
            if raw_type in {"MARKET", "AUCTION"}
            else "limit"
            if raw_type
            in {"NORMAL", "ABSOLUTE_LIMIT", "AUCTION_LIMIT", "SPECIAL_LIMIT", "SPECIAL_LIMIT_ALL"}
            else "other"
        )
        stops.append(
            {
                "symbol": normalize_symbol(f"{ticker}.{market}"),
                "quantity": str(remaining),
                "trigger_price": positive(order.get("aux_price")),
                "limit_price": positive(order.get("price")),
                "order_kind": kind,
                "side": "buy" if order["trd_side"] == "BUY" else "sell",
                "broker_order_id": str(order["order_id"])
                if order.get("order_id") is not None
                else None,
                "raw_type": raw_type,
                "observed_at": observed,
                "trailing_percent": positive(order.get("trail_value"))
                if order.get("trail_type") == "PERCENTAGE"
                else None,
                "status": "active",
                "evidence": "broker_verified",
            }
        )
    # Missing debt/frozen-cash information is not silently treated as zero.
    if not {"cash", "frozen_cash", "debt_cash", "total_assets"} <= balance.keys():
        raise ValueError("Futu account response lacks required cash/debt fields")
    frozen = number(balance["frozen_cash"])
    debt = number(balance["debt_cash"])
    if frozen < 0 or debt < 0:
        raise ValueError("Futu frozen cash/debt values are unavailable")
    cash = number(balance["cash"]) - frozen
    return SnapshotInput.model_validate(
        {
            "account_id": account_id,
            "broker": "futu",
            "label": account_id,
            "external_id": str(uuid4()),
            "as_of": now(),
            "base_currency": base_currency,
            "net_assets": str(number(balance["total_assets"])),
            "cash": str(cash),
            "margin_used": debt > 0 or cash < 0,
            "pending_buy_orders": pending_buys,
            "monthly_drawdown": None,
            "record_origin": "broker_api",
            "positions": normalized,
            "orders": stops,
        }
    )


def sync(account_id: str, base_currency: str) -> dict:
    cfg = settings()
    market_name = {"USD": "US", "HKD": "HK", "CNY": "CN"}.get(base_currency)
    if market_name is None:
        raise ValueError("base_currency must be CNY, HKD or USD")
    try:
        with socket.create_connection((cfg.futu_host, cfg.futu_port), timeout=3):
            pass
    except OSError:
        raise RuntimeError("Futu OpenD gateway unavailable; start OpenD and log in") from None
    try:
        from futu import RET_OK, Currency, OpenSecTradeContext, SecurityFirm, TrdEnv, TrdMarket
    except ImportError:
        raise ValueError("Install the Futu SDK: uv sync --extra futu") from None
    with contextlib.redirect_stdout(sys.stderr):
        context = OpenSecTradeContext(
            filter_trdmarket=getattr(TrdMarket, market_name),
            host=cfg.futu_host,
            port=cfg.futu_port,
            security_firm=getattr(SecurityFirm, cfg.futu_security_firm),
        )
        try:
            ret, accounts = context.get_acc_list()
            if ret != RET_OK:
                raise RuntimeError("Unable to read Futu accounts")
            real = accounts[accounts["trd_env"] == TrdEnv.REAL]
            if cfg.futu_acc_id:
                real = real[real["acc_id"] == int(cfg.futu_acc_id)]
            if len(real) != 1:
                raise ValueError("Select exactly one REAL account with TRADEGUARD_FUTU_ACC_ID")
            remote_id = int(real.iloc[0]["acc_id"])
            common = {"trd_env": TrdEnv.REAL, "acc_id": remote_id, "refresh_cache": True}
            ret, positions = context.position_list_query(**common)
            if ret != RET_OK:
                raise RuntimeError("Futu position query failed; no snapshot saved")
            ret, orders = context.order_list_query(**common)
            if ret != RET_OK:
                raise RuntimeError("Futu order query failed; no snapshot saved")
            ret, balances = context.accinfo_query(
                **common, currency=getattr(Currency, base_currency)
            )
            if ret != RET_OK or len(balances) != 1:
                raise RuntimeError("Futu account query failed; no snapshot saved")
            snapshot = normalize_snapshot(
                account_id,
                base_currency,
                balances.iloc[0].to_dict(),
                positions.to_dict(orient="records"),
                orders.to_dict(orient="records"),
            )
        finally:
            context.close()
    return {
        **save_snapshot(snapshot, broker_verified=True),
        "warnings": ["Monthly drawdown and FX require additional evidence."],
    }
