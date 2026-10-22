"""Read genuine prior account/position/order observations without treating them as live."""

import hashlib
from datetime import timezone
from decimal import Decimal

from sqlalchemy import text

from tradeguard.config import settings
from tradeguard.db import session
from tradeguard.db.models import Account
from tradeguard.db.readonly import open_readonly
from tradeguard.market.schemas import normalize_symbol
from tradeguard.portfolio.schemas import SnapshotInput
from tradeguard.portfolio.service import save_snapshot


def number(value):
    if value is None:
        return None
    n = Decimal(str(value))
    return n if n.is_finite() else None


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def import_portfolio() -> dict:
    cfg = settings()
    if cfg.portfolio_source_url is None:
        raise ValueError("Configure TRADEGUARD_PORTFOLIO_SOURCE_URL")
    remote_engine = open_readonly(
        cfg.portfolio_source_url.get_secret_value(),
        connect_args={"connect_timeout": 10, "read_timeout": 30},
    )
    saved, empty = [], []
    try:
        with remote_engine.connect() as remote:
            remote.execute(text("SET SESSION TRANSACTION READ ONLY"))
            remote.commit()
            accounts = (
                remote.execute(text("SELECT * FROM pt_accounts ORDER BY display_order,id"))
                .mappings()
                .all()
            )
            runs = (
                remote.execute(
                    text(
                        "SELECT * FROM pt_broker_sync_runs WHERE status='success' ORDER BY id DESC"
                    )
                )
                .mappings()
                .all()
            )
            positions = remote.execute(text("SELECT * FROM pt_position_snapshots")).mappings().all()
            orders = remote.execute(text("SELECT * FROM pt_order_snapshots")).mappings().all()
            balances = remote.execute(text("SELECT * FROM pt_account_snapshots")).mappings().all()
            lots = (
                remote.execute(text("SELECT * FROM pt_position_lots WHERE active=1"))
                .mappings()
                .all()
            )
        for a in accounts:
            run = next((r for r in runs if r["broker"] == a["broker"]), None)
            if run is None:
                with session() as db, db.begin():
                    account_id = f"{a['broker']}-{a['id']}"
                    if db.get(Account, account_id) is None:
                        db.add(Account(id=account_id, broker=a["broker"], label=a["account_label"]))
                empty.append({"broker": a["broker"], "reason": "no_successful_source_sync"})
                continue

            def matches(row, a=a, run=run):
                return (
                    row["broker"] == a["broker"]
                    and row["account_label"] == a["account_label"]
                    and row["sync_run_id"] == run["id"]
                )

            observed = aware(run["finished_at"] or run["started_at"])
            bs = [b for b in balances if matches(b) and b["net_assets"] is not None]
            balance = next((b for b in bs if b["segment"] == "UNIFIED"), bs[0] if bs else {})
            currency = a["base_currency"] or balance.get("currency") or "CNY"
            net_assets = (
                number(balance.get("net_assets")) if balance.get("currency") == currency else None
            )
            normalized_positions, normalized_orders = [], []
            for p in (p for p in positions if matches(p)):
                qty = number(p["qty"])
                if not qty:
                    continue
                try:
                    symbol, kind = normalize_symbol(p["symbol"]), "stock"
                except ValueError:
                    symbol, kind = p["symbol"], "other"
                cost = number(p["avg_cost"])
                normalized_positions.append(
                    {
                        "symbol": symbol,
                        "instrument_kind": kind,
                        "name": p["name"],
                        "currency": p["currency"],
                        "quantity": qty,
                        "market_value": number(p["market_value"]),
                        "average_cost": cost if cost and cost > 0 else None,
                        "observed_at": aware(p["synced_at"]),
                    }
                )
            for o in (o for o in orders if matches(o)):
                kind = {
                    "STOP_LOSS": "stop_loss",
                    "TAKE_PROFIT": "take_profit",
                    "TRAILING": "trailing",
                    "LIMIT": "limit",
                    "MARKET": "market",
                }.get(o["order_kind"], "other")
                normalized_orders.append(
                    {
                        "symbol": normalize_symbol(o["symbol"]),
                        "quantity": number(o["qty"]),
                        "order_kind": kind,
                        "side": "sell" if "sell" in o["side"].lower() else "buy",
                        "trigger_price": number(o["trigger_price"]),
                        "limit_price": number(o["limit_price"]),
                        "status": "unknown",
                        "evidence": "broker_verified",
                        "broker_order_id": o["external_order_id"],
                        "raw_type": o["order_type_raw"],
                        "observed_at": aware(o["synced_at"]),
                    }
                )
            for lot in (item for item in lots if item["account_id"] == a["id"]):
                for field, kind in [
                    ("planned_stop", "stop_loss"),
                    ("planned_take_profit", "take_profit"),
                    ("trailing_stop_pct", "trailing"),
                ]:
                    value = number(lot[field])
                    if not value or value <= 0:
                        continue
                    q = number(lot["qty_planned"])
                    normalized_orders.append(
                        {
                            "symbol": normalize_symbol(lot["symbol"]),
                            "quantity": q if q and q > 0 else None,
                            "order_kind": kind,
                            "trigger_price": value if kind != "trailing" else None,
                            "trailing_percent": value if kind == "trailing" else None,
                            "activation_price": number(lot["trailing_activation_price"]),
                            "status": "unknown",
                            "evidence": "manually_confirmed"
                            if "已挂" in (lot["note"] or "")
                            else "planned",
                            "broker_order_id": f"manual-lot-{lot['id']}-{kind}",
                            "observed_at": aware(lot["updated_at"]),
                            "note": lot["note"],
                        }
                    )
            asset_time = aware(balance["synced_at"]) if balance else None
            payload = {
                "account_id": f"{a['broker']}-{a['id']}",
                "broker": a["broker"],
                "label": a["account_label"],
                "external_id": "legacy-v2-"
                + str(run["id"])
                + "-"
                + hashlib.sha256(str(normalized_orders).encode()).hexdigest()[:16],
                "as_of": observed,
                "assets_as_of": asset_time,
                "base_currency": currency,
                "net_assets": net_assets or number(a["manual_net_value"]),
                "cash": number(balance.get("cash"))
                if balance.get("currency") == currency
                else None,
                "margin_used": bool(balance["margin_in_use"])
                if balance and balance.get("margin_in_use") is not None
                else None,
                "positions": normalized_positions,
                "orders": normalized_orders,
                "record_origin": "legacy_broker_cache"
                if a["broker"] in {"futu", "longbridge", "ibkr"}
                else "legacy_manual",
                "statement": "Imported existing real account observations; timestamps retained; not a new broker synchronization.",
                "asset_scope": "other" if "fund" in (a["capital_usage"] or "") else "stock",
            }
            result = save_snapshot(SnapshotInput.model_validate(payload), broker_verified=True)
            saved.append(
                {
                    "account_id": payload["account_id"],
                    "positions": len(normalized_positions),
                    "orders": len(normalized_orders),
                    "as_of": observed.isoformat(),
                    **result,
                }
            )
        return {"accounts": saved, "without_observation": empty}
    finally:
        remote_engine.dispose()
