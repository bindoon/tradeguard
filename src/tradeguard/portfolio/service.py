from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert

from tradeguard.db import session
from tradeguard.db.models import Account, PortfolioSnapshot, Security, now
from tradeguard.portfolio.schemas import ManualPatch, Position, SnapshotInput


def save_snapshot(snapshot: SnapshotInput, *, broker_verified: bool = False) -> dict:
    if snapshot.as_of > now() + timedelta(minutes=1):
        raise ValueError("Snapshot is in the future")
    if not broker_verified and any(o.evidence == "broker_verified" for o in snapshot.orders):
        raise ValueError("Manual imports cannot claim broker-verified orders")
    payload = snapshot.model_dump(mode="json")
    with session() as db, db.begin():
        previous = db.scalar(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.account_id == snapshot.account_id,
                PortfolioSnapshot.external_id == snapshot.external_id,
            )
        )
        if previous:
            if previous.payload != payload:
                raise ValueError("Snapshot ID already exists with different content")
            return {"snapshot_id": previous.id, "reused": True}
        account = db.get(Account, snapshot.account_id)
        if account and account.broker != snapshot.broker:
            raise ValueError("Account broker cannot change")
        if account is None:
            db.add(Account(id=snapshot.account_id, broker=snapshot.broker, label=snapshot.label))
            db.flush()
        from tradeguard.market.schemas import currency_for

        for position in snapshot.positions:
            if position.instrument_kind != "stock":
                continue
            symbol = position.symbol
            currency = currency_for(symbol)
            stmt = insert(Security).values(
                symbol=symbol,
                name=position.name or symbol,
                currency=currency,
                market="CN" if currency == "CNY" else symbol.rsplit(".", 1)[1],
            )
            db.execute(stmt.on_duplicate_key_update(symbol=stmt.inserted.symbol))
        row = PortfolioSnapshot(
            account_id=snapshot.account_id,
            external_id=snapshot.external_id,
            as_of=snapshot.as_of,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return {
            "snapshot_id": row.id,
            "reused": False,
            "position_count": len(snapshot.positions),
            "as_of": snapshot.as_of.isoformat(),
        }


def latest(account_id: str) -> PortfolioSnapshot | None:
    with session() as db:
        return db.scalar(
            select(PortfolioSnapshot)
            .where(
                PortfolioSnapshot.account_id == account_id,
            )
            .order_by(
                PortfolioSnapshot.as_of.desc(),
                PortfolioSnapshot.recorded_at.desc(),
                PortfolioSnapshot.id.desc(),
            )
            .limit(1)
        )


def report(account_id: str) -> dict:
    row = latest(account_id)
    if row is None:
        raise ValueError("No complete snapshot for this account")
    return {"snapshot_id": row.id, **row.payload}


def manual_update(account_id: str, patch: ManualPatch) -> dict:
    """Merge explicit user facts into a new immutable snapshot; retain older observations."""
    row = latest(account_id)
    with session() as db:
        account = db.get(Account, account_id)
        if account is None:
            raise ValueError("Account not found; create an account first")
    previous = SnapshotInput.model_validate(row.payload) if row else None
    currency = patch.base_currency or (previous.base_currency if previous else None)
    if currency is None:
        raise ValueError("base_currency is required for a first manual update")
    payload: dict[str, Any] = (
        previous.model_dump(mode="json")
        if previous
        else {
            "account_id": account_id,
            "broker": account.broker,
            "label": account.label,
            "base_currency": currency,
            "positions": [],
            "orders": [],
        }
    )
    if previous:
        payload["assets_as_of"] = payload.get("assets_as_of") or previous.as_of.isoformat()
        for item in payload["positions"] + payload["orders"]:
            item["observed_at"] = item.get("observed_at") or previous.as_of.isoformat()
    by_symbol = {p["symbol"]: p for p in payload["positions"]}
    from decimal import Decimal
    from uuid import uuid4

    from tradeguard.market.schemas import currency_for, normalize_symbol

    for item in patch.positions:
        update = item.model_dump(exclude_unset=True)
        symbol = normalize_symbol(update["symbol"])
        old = by_symbol.get(symbol, {})
        merged = {
            **old,
            **update,
            "symbol": symbol,
            "currency": currency_for(symbol),
            "observed_at": patch.as_of.isoformat(),
        }
        if "quantity" in update and Decimal(str(update["quantity"])) == 0:
            by_symbol.pop(symbol, None)
            continue
        if "quantity" in update and "market_value" not in update:
            merged["market_value"] = None
        by_symbol[symbol] = Position.model_validate(merged).model_dump(mode="json")
    payload.update(
        account_id=account_id,
        positions=list(by_symbol.values()),
        external_id=str(uuid4()),
        as_of=patch.as_of.isoformat(),
        record_origin="manual",
        base_currency=currency,
        statement=patch.statement,
        previous_snapshot_id=row.id if row else None,
    )
    for field in ("net_assets", "cash", "margin_used"):
        if field in patch.model_fields_set:
            payload[field] = getattr(patch, field)
    if {"net_assets", "cash", "margin_used"} <= patch.model_fields_set:
        payload["assets_as_of"] = patch.as_of
    if patch.orders is not None:
        if any(o.evidence == "broker_verified" for o in patch.orders):
            raise ValueError("Agent updates cannot claim broker verification")
        existing = [] if patch.replace_orders else list(payload["orders"])
        for order in patch.orders:
            item = order.model_copy(update={"observed_at": patch.as_of}).model_dump(mode="json")
            matches = [
                i
                for i, old in enumerate(existing)
                if (order.broker_order_id and old.get("broker_order_id") == order.broker_order_id)
                or (
                    not order.broker_order_id
                    and old["symbol"] == order.symbol
                    and old.get("order_kind", "stop_loss") == order.order_kind
                    and old.get("side", "sell") == order.side
                )
            ]
            if len(matches) > 1:
                raise ValueError("Several matching orders exist; specify broker_order_id")
            if matches:
                old = existing[matches[0]]
                existing[matches[0]] = {
                    **old,
                    **order.model_dump(mode="json", exclude_unset=True),
                    "observed_at": patch.as_of.isoformat(),
                }
            else:
                existing.append(item)
        payload["orders"] = existing
    snapshot = SnapshotInput.model_validate(payload)
    # Broker observations retained from the previous snapshot remain unchanged evidence.
    return save_snapshot(snapshot, broker_verified=True)


def create_account(account_id: str, broker: str, label: str) -> dict:
    if not account_id or len(account_id) > 60 or not broker or not label:
        raise ValueError("Provide account id, broker and label")
    with session() as db, db.begin():
        if db.get(Account, account_id) is not None:
            raise ValueError("Account already exists")
        db.add(Account(id=account_id, broker=broker, label=label))
    return {"account_id": account_id}
