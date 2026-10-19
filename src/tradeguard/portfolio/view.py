from datetime import timedelta

from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import Account, PortfolioSnapshot, Run, now
from tradeguard.portfolio.schemas import SnapshotInput


def accounts_view():
    items = []
    with session() as db:
        accounts = db.scalars(select(Account).order_by(Account.label)).all()
        for a in accounts:
            row = db.scalar(
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.account_id == a.id)
                .order_by(
                    PortfolioSnapshot.as_of.desc(),
                    PortfolioSnapshot.recorded_at.desc(),
                    PortfolioSnapshot.id.desc(),
                )
                .limit(1)
            )
            syncs = db.scalars(
                select(Run)
                .where(Run.kind == "account_sync")
                .order_by(Run.started_at.desc())
                .limit(100)
            ).all()
            last_sync = next((r for r in syncs if r.details.get("account_id") == a.id), None)
            if row is None:
                items.append(
                    {
                        "id": a.id,
                        "label": a.label,
                        "broker": a.broker,
                        "snapshot": None,
                        "lastSync": last_sync.details if last_sync else None,
                    }
                )
                continue
            snapshot = SnapshotInput.model_validate(row.payload)
            payload = snapshot.model_dump(mode="json")
            payload["snapshot_id"] = row.id
            payload["stale"] = now() - snapshot.as_of > timedelta(hours=24)
            for i, p in enumerate(snapshot.positions):
                pnl = (
                    p.market_value - p.average_cost * p.quantity
                    if p.market_value is not None and p.average_cost is not None
                    else None
                )
                cost = p.average_cost * p.quantity if p.average_cost is not None else None
                payload["positions"][i]["pnl"] = str(pnl) if pnl is not None else None
                payload["positions"][i]["pnl_percent"] = (
                    str(pnl / cost) if pnl is not None and cost else None
                )
            items.append(
                {
                    "id": a.id,
                    "label": a.label,
                    "broker": a.broker,
                    "snapshot": payload,
                    "lastSync": last_sync.details if last_sync else None,
                }
            )
    return {
        "accounts": items,
        "as_of": now().isoformat(),
        "note": "真实持仓按账户和币种展示；历史快照不会伪装为本次实时同步。",
    }


def sync_account_view(account_id):
    with session() as db, db.begin():
        account = db.get(Account, account_id)
        if account is None:
            raise ValueError("账户不存在")
        snapshot = db.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id == account_id)
            .order_by(PortfolioSnapshot.as_of.desc())
            .limit(1)
        )
        if account.broker not in {"longbridge", "futu"}:
            raise ValueError("此账户没有已配置的自动接口，请让 Agent 根据你的口述更新真实记录")
        currency = snapshot.payload["base_currency"] if snapshot else "HKD"
        broker = account.broker
        run: Run | None = Run(
            kind="account_sync",
            status="running",
            details={"account_id": account_id, "broker": broker},
        )
        db.add(run)
        db.flush()
        assert run is not None
        run_id = run.id
    try:
        if broker == "longbridge":
            from tradeguard.portfolio.longbridge import sync
        else:
            from tradeguard.portfolio.futu import sync
        result = sync(account_id, currency)
    except Exception as exc:
        error = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        with session() as db, db.begin():
            run = db.get(Run, run_id)
            assert run is not None
            run.status, run.finished_at = "failed", now()
            run.details = {
                **run.details,
                "error": error,
                "at": now().isoformat(),
                "status": "failed",
            }
        return {"status": "failed", "error": error, "kept_previous_snapshot": True}
    with session() as db, db.begin():
        run = db.get(Run, run_id)
        assert run is not None
        run.status, run.finished_at = "success", now()
        run.details = {
            **run.details,
            "status": "success",
            "at": now().isoformat(),
            "snapshot_id": result["snapshot_id"],
        }
    return {"status": "success", **result}
