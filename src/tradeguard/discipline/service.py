from datetime import datetime, timedelta
from decimal import Decimal

from tradeguard.db import session
from tradeguard.db.models import DisciplineCheck, RuleProfile, now
from tradeguard.discipline.schemas import Intent, Rules
from tradeguard.portfolio.schemas import SnapshotInput
from tradeguard.portfolio.service import latest


def evaluate(intent: Intent, rules: Rules, snapshot: SnapshotInput | None, at: datetime) -> dict:
    blocked: list[str] = []
    missing: list[str] = []
    metrics: dict = {}
    if snapshot is None:
        return {
            "decision": "needs_input",
            "blocked": [],
            "missing": ["portfolio_snapshot"],
            "metrics": {},
            "warnings": [],
        }
    if snapshot.account_id != intent.account_id:
        raise ValueError("Snapshot account does not match intent")
    if (
        not timedelta(minutes=-1)
        <= at - snapshot.as_of
        <= timedelta(minutes=rules.snapshot_max_age_minutes)
    ):
        missing.append("fresh_portfolio_snapshot")
    if snapshot.assets_as_of and at - snapshot.assets_as_of > timedelta(
        minutes=rules.snapshot_max_age_minutes
    ):
        missing.append("fresh_account_assets")
    if snapshot.margin_used or (snapshot.cash is not None and snapshot.cash < 0):
        blocked.append("leverage_forbidden")
    if snapshot.margin_used is None:
        missing.append("margin_status")
    if snapshot.net_assets is None or snapshot.net_assets <= 0:
        missing.append("net_assets")
    if snapshot.cash is None:
        missing.append("cash")
    if snapshot.pending_buy_orders:
        missing.append("pending_buy_orders_require_exposure_review")
    if snapshot.monthly_drawdown is None:
        missing.append("monthly_drawdown")
    elif snapshot.monthly_drawdown <= -rules.monthly_drawdown_limit:
        blocked.append("monthly_drawdown_circuit_breaker")

    def fx(currency: str) -> Decimal | None:
        if currency == snapshot.base_currency:
            return Decimal(1)
        rate = snapshot.fx_to_base.get(currency)
        if rate is None:
            missing.append(f"fx:{currency}/{snapshot.base_currency}")
        return rate

    rate = fx(intent.currency)
    holding = next((p for p in snapshot.positions if p.symbol == intent.symbol), None)
    if intent.action == "add" and holding is None:
        missing.append("existing_position_for_add")
    if intent.action == "buy" and holding is not None:
        missing.append("use_add_for_existing_position")
    if holding and intent.style == "trend":
        if holding.average_cost is None:
            missing.append("average_cost")
        elif intent.price <= holding.average_cost:
            blocked.append("trend_averaging_down")
    if intent.style == "value" and holding:
        missing.append("value_add_requires_human_fundamental_review")

    # All existing positions must have evidence of active protective orders.
    for p in snapshot.positions:
        if p.quantity < 0 or p.instrument_kind != "stock":
            missing.append(f"manual_instrument_review:{p.symbol}")
        if p.observed_at and at - p.observed_at > timedelta(minutes=rules.snapshot_max_age_minutes):
            missing.append(f"fresh_position:{p.symbol}")
        covered = sum(
            (
                o.quantity or Decimal(0)
                for o in snapshot.orders
                if o.symbol == p.symbol
                and o.status == "active"
                and o.order_kind in {"stop_loss", "trailing"}
                and o.side == "sell"
                and (
                    o.observed_at is None
                    or at - o.observed_at <= timedelta(minutes=rules.snapshot_max_age_minutes)
                )
                and (
                    o.evidence == "broker_verified"
                    or (o.evidence == "manually_confirmed" and rules.allow_manual_stop_confirmation)
                )
            ),
            Decimal(0),
        )
        if covered < p.quantity:
            missing.append(f"verified_stop_coverage:{p.symbol}")
    if intent.stop_price is None:
        missing.append("stop_price")
    if intent.stop_evidence != "manually_confirmed" or not rules.allow_manual_stop_confirmation:
        missing.append("manual_confirmation_of_stop_plan")
    if holding and holding.market_value is None:
        missing.append("position_market_value")
    if (
        rate is not None
        and snapshot.net_assets is not None
        and snapshot.net_assets > 0
        and snapshot.cash is not None
        and (not holding or holding.market_value is not None)
    ):
        cost = (intent.quantity * intent.price + intent.fees) * rate
        holding_value = (
            holding.market_value if holding and holding.market_value is not None else Decimal(0)
        )
        exposure = holding_value * rate + cost
        ratio = exposure / snapshot.net_assets
        metrics.update(
            cost_base=str(cost),
            projected_stock_ratio=str(ratio),
            base_currency=snapshot.base_currency,
        )
        if ratio > rules.single_stock_limit:
            blocked.append("single_stock_limit")
        if cost > snapshot.cash:
            blocked.append("insufficient_cash")
        if intent.stop_price is not None:
            loss = (intent.quantity * (intent.price - intent.stop_price) + intent.fees) * rate
            metrics["planned_loss_ratio"] = str(loss / snapshot.net_assets)
            if loss / snapshot.net_assets > rules.max_trade_loss:
                blocked.append("max_trade_loss")
    return {
        "decision": "blocked" if blocked else "needs_input" if missing else "pass",
        "blocked": blocked,
        "missing": sorted(set(missing)),
        "metrics": metrics,
        "warnings": [
            "Assessment only: confirm an effective broker stop after execution; "
            "gaps and slippage can exceed the planned loss."
        ],
    }


def save_rules(rules: Rules) -> dict:
    with session() as db, db.begin():
        row = RuleProfile(name=rules.name, rules=rules.model_dump(mode="json"))
        db.add(row)
        db.flush()
        return {"profile_id": row.id, "name": row.name}


def check(intent: Intent, profile_id: str) -> dict:
    with session() as db, db.begin():
        profile = db.get(RuleProfile, profile_id)
        if profile is None:
            raise ValueError("Rule profile not found; import explicit rules first")
        snapshot_row = latest(intent.account_id)
        snapshot = SnapshotInput.model_validate(snapshot_row.payload) if snapshot_row else None
        result = evaluate(intent, Rules.model_validate(profile.rules), snapshot, now())
        row = DisciplineCheck(
            rule_profile_id=profile.id,
            snapshot_id=snapshot_row.id if snapshot_row else None,
            intent=intent.model_dump(mode="json"),
            result=result,
        )
        db.add(row)
        db.flush()
        return {
            "check_id": row.id,
            "rule_profile_id": profile.id,
            "snapshot_id": row.snapshot_id,
            **result,
        }
