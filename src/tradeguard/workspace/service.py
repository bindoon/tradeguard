from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert

from tradeguard.db import session
from tradeguard.db.models import (
    Account,
    DailyBar,
    DisciplineCheck,
    Notification,
    PortfolioSnapshot,
    PriceAlert,
    RuleProfile,
    Run,
    ScanResult,
    ScanSummary,
    Security,
    WatchItem,
    now,
    uid,
)
from tradeguard.market.schemas import currency_for
from tradeguard.portfolio.schemas import SnapshotInput
from tradeguard.report import daily_report
from tradeguard.workspace.schemas import AlertInput, Scope, WatchInput


def today() -> date:
    return now().astimezone(ZoneInfo("Asia/Shanghai")).date()


def bounded_day(target: date | None) -> date:
    target = target or today()
    if target > today():
        raise ValueError("不能使用未来交易日")
    return target


def security_in_scope(db, symbol: str, scope: Scope):
    security = db.get(Security, symbol)
    if security is None or security.market != scope.market:
        raise ValueError("该市场没有此标的，请先登记证券或导入行情")
    return security


def latest_bar(db, symbol: str, scope: Scope, target: date):
    return db.scalar(
        select(DailyBar)
        .where(
            DailyBar.symbol == symbol,
            DailyBar.source == scope.source,
            DailyBar.adjustment == scope.adjustment,
            DailyBar.trade_date <= target,
        )
        .order_by(DailyBar.trade_date.desc())
        .limit(1)
    )


def latest_signal(db, symbol: str, scope: Scope, target: date):
    return db.scalar(
        select(ScanResult)
        .join(Run, Run.id == ScanResult.run_id)
        .where(
            ScanResult.symbol == symbol,
            ScanResult.trade_date <= target,
            Run.market == scope.market,
            Run.status.in_(["success", "partial"]),
            Run.kind == "scan",
            Run.details["source"].as_string() == scope.source,
            func.coalesce(Run.details["adjustment"].as_string(), "forward") == scope.adjustment,
        )
        .order_by(ScanResult.trade_date.desc(), Run.started_at.desc())
        .limit(1)
    )


def add_watch(payload: WatchInput) -> dict:
    with session() as db, db.begin():
        security_in_scope(db, payload.symbol, payload)
        if payload.scan_run_id:
            run = db.get(Run, payload.scan_run_id)
            if (
                run is None
                or run.kind != "scan"
                or run.market != payload.market
                or run.details.get("source") != payload.source
                or run.details.get("adjustment", "forward") != payload.adjustment
                or run.status not in {"success", "partial"}
                or db.get(ScanResult, (payload.scan_run_id, payload.symbol)) is None
            ):
                raise ValueError("关联扫描与市场、来源或复权不符")
        existing = db.scalar(
            select(WatchItem)
            .where(
                WatchItem.symbol == payload.symbol,
                WatchItem.source == payload.source,
                WatchItem.adjustment == payload.adjustment,
            )
            .with_for_update()
        )
        if existing:
            existing.reason = payload.reason
            existing.scan_run_id = payload.scan_run_id
            row = existing
        else:
            signal = latest_signal(db, payload.symbol, payload, today())
            row = WatchItem(
                **payload.model_dump(), last_signal_run_id=signal.run_id if signal else None
            )
            db.add(row)
        db.flush()
        return {"id": row.id, "symbol": row.symbol}


def remove_watch(identifier: str) -> dict:
    with session() as db, db.begin():
        row = db.get(WatchItem, identifier)
        if row is None:
            raise ValueError("自选记录不存在")
        db.delete(row)
    return {"removed": identifier}


def watches(scope: Scope, target: date | None = None) -> list[dict]:
    target = bounded_day(target)
    with session() as db:
        rows = db.scalars(
            select(WatchItem)
            .where(
                WatchItem.market == scope.market,
                WatchItem.source == scope.source,
                WatchItem.adjustment == scope.adjustment,
            )
            .order_by(WatchItem.created_at.desc())
        ).all()
        result = []
        for row in rows:
            security = security_in_scope(db, row.symbol, scope)
            bar = latest_bar(db, row.symbol, scope, target)
            signal = latest_signal(db, row.symbol, scope, target)
            result.append(
                {
                    "id": row.id,
                    "symbol": row.symbol,
                    "name": security.name,
                    "currency": security.currency,
                    "reason": row.reason,
                    "source": row.source,
                    "adjustment": row.adjustment,
                    "scan_run_id": row.scan_run_id,
                    "created_at": row.created_at.isoformat(),
                    "close": str(bar.close) if bar else None,
                    "price_date": str(bar.trade_date) if bar else None,
                    "signal_date": str(signal.trade_date) if signal else None,
                    "strategies": signal.hits if signal else [],
                    "resonance_count": len(signal.hits) if signal else None,
                }
            )
        return result


def search(scope: Scope, query: str) -> list[dict]:
    query = query.strip()[:80]
    if not query:
        return []
    with session() as db:
        rows = db.scalars(
            select(Security)
            .where(
                Security.market == scope.market,
                Security.symbol.contains(query.upper(), autoescape=True)
                | Security.name.contains(query, autoescape=True),
            )
            .order_by(Security.symbol)
            .limit(30)
        ).all()
        return [
            {
                "symbol": s.symbol,
                "name": s.name,
                "currency": s.currency,
                "industry": s.industry,
                "price_date": str(bar.trade_date)
                if (bar := latest_bar(db, s.symbol, scope, today()))
                else None,
            }
            for s in rows
        ]


def add_alert(payload: AlertInput) -> dict:
    with session() as db, db.begin():
        security_in_scope(db, payload.symbol, payload)
        row = PriceAlert(**payload.model_dump())
        db.add(row)
        db.flush()
        return {"id": row.id, "active": row.active}


def alerts(scope: Scope) -> list[dict]:
    with session() as db:
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "condition": r.condition,
                "target_price": str(r.target_price),
                "currency": currency_for(r.symbol),
                "active": r.active,
                "source": r.source,
                "adjustment": r.adjustment,
            }
            for r in db.scalars(
                select(PriceAlert)
                .where(
                    PriceAlert.market == scope.market,
                    PriceAlert.source == scope.source,
                    PriceAlert.adjustment == scope.adjustment,
                )
                .order_by(PriceAlert.created_at.desc())
            ).all()
        ]


def cancel_alert(identifier: str) -> dict:
    with session() as db, db.begin():
        row = db.get(PriceAlert, identifier)
        if row is None:
            raise ValueError("提醒条件不存在")
        row.active = False
    return {"id": identifier, "active": False}


def inbox(scope: Scope) -> list[dict]:
    with session() as db:
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "symbol": r.symbol,
                "title": r.title,
                "evidence": r.evidence,
                "read": r.read,
                "created_at": r.created_at.isoformat(),
            }
            for r in db.scalars(
                select(Notification)
                .where(
                    Notification.market == scope.market,
                    Notification.source == scope.source,
                    Notification.adjustment == scope.adjustment,
                )
                .order_by(Notification.created_at.desc())
                .limit(100)
            ).all()
        ]


def mark_read(identifier: str) -> dict:
    with session() as db, db.begin():
        row = db.get(Notification, identifier)
        if row is None:
            raise ValueError("提醒记录不存在")
        row.read = True
    return {"id": identifier, "read": True}


def notify(db, scope: Scope, key: str, kind: str, symbol: str | None, title: str, evidence: dict):
    statement = insert(Notification).values(
        id=uid(),
        event_key=sha256(key.encode()).hexdigest(),
        kind=kind,
        symbol=symbol,
        title=title,
        evidence=evidence,
        read=False,
        created_at=now(),
        **scope.model_dump(),
    )
    db.execute(statement.on_duplicate_key_update(event_key=statement.inserted.event_key))


def refresh(scope: Scope, target: date | None = None) -> dict:
    """Evaluate saved observations only. No provider requests, emails or broker writes."""
    target = bounded_day(target)
    with session() as db, db.begin():
        rules = db.scalars(
            select(PriceAlert)
            .where(
                PriceAlert.market == scope.market,
                PriceAlert.source == scope.source,
                PriceAlert.adjustment == scope.adjustment,
                PriceAlert.active.is_(True),
            )
            .with_for_update()
        ).all()
        for rule in rules:
            bar = latest_bar(db, rule.symbol, scope, target)
            # A condition created today cannot be fired by an old imported observation.
            if (
                bar is None
                or bar.trade_date < rule.created_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
            ):
                continue
            hit = (
                bar.close >= rule.target_price
                if rule.condition == "above"
                else bar.close <= rule.target_price
            )
            if hit:
                notify(
                    db,
                    scope,
                    "price:" + rule.id,
                    "price",
                    rule.symbol,
                    f"{rule.symbol} 缓存收盘价达到提醒条件",
                    {
                        "trade_date": str(bar.trade_date),
                        "price": str(bar.close),
                        "target_price": str(rule.target_price),
                        "condition": rule.condition,
                        "currency": currency_for(rule.symbol),
                        "mode": "cached_close",
                    },
                )
                rule.active = False
        watch_rows = db.scalars(
            select(WatchItem)
            .where(
                WatchItem.market == scope.market,
                WatchItem.source == scope.source,
                WatchItem.adjustment == scope.adjustment,
            )
            .with_for_update()
        ).all()
        for watch in watch_rows:
            signal = latest_signal(db, watch.symbol, scope, target)
            if signal and signal.run_id != watch.last_signal_run_id:
                run = db.get(Run, signal.run_id)
                if run and run.started_at >= watch.created_at:
                    notify(
                        db,
                        scope,
                        f"signal:{watch.id}:{signal.run_id}",
                        "signal",
                        watch.symbol,
                        f"{watch.symbol} 出现新的策略信号",
                        {
                            "trade_date": str(signal.trade_date),
                            "run_id": signal.run_id,
                            "strategies": signal.hits,
                            "mode": "saved_scan",
                        },
                    )
                    watch.last_signal_run_id = signal.run_id
        # Snapshot attention items are local-only, and only evaluated for today's workspace.
        if target == today():
            for account in db.scalars(select(Account)).all():
                row = db.scalar(
                    select(PortfolioSnapshot)
                    .where(
                        PortfolioSnapshot.account_id == account.id,
                    )
                    .order_by(PortfolioSnapshot.as_of.desc(), PortfolioSnapshot.recorded_at.desc())
                    .limit(1)
                )
                if row is None or now() - row.as_of > timedelta(hours=24):
                    notify(
                        db,
                        scope,
                        f"snapshot:{account.id}:{row.id if row else 'none'}:{scope.market}:{scope.source}:{scope.adjustment}",
                        "snapshot",
                        None,
                        f"{account.label} 持仓观察待更新",
                        {
                            "account_id": account.id,
                            "snapshot_id": row.id if row else None,
                            "as_of": row.as_of.isoformat() if row else None,
                            "reason": "older_than_24h" if row else "missing_snapshot",
                        },
                    )
    return {"status": "success", "mode": "cached_observations", "evaluated_through": str(target)}


def position_reviews(scope: Scope) -> list[dict]:
    result = []
    with session() as db:
        for account in db.scalars(select(Account)).all():
            row = db.scalar(
                select(PortfolioSnapshot)
                .where(
                    PortfolioSnapshot.account_id == account.id,
                )
                .order_by(PortfolioSnapshot.as_of.desc(), PortfolioSnapshot.recorded_at.desc())
                .limit(1)
            )
            if row is None:
                result.append(
                    {
                        "account_label": account.label,
                        "symbol": None,
                        "decision": "needs_input",
                        "reasons": [
                            "缺少完整账户快照：请同步券商；无接口账户请提供账户资产、现金、全部持仓及观察时间，不能把未知当作空仓"
                        ],
                    }
                )
                continue
            snap = SnapshotInput.model_validate(row.payload)
            for position in snap.positions:
                if (
                    position.instrument_kind != "stock"
                    or currency_for(position.symbol)
                    != {
                        "CN": "CNY",
                        "US": "USD",
                        "HK": "HKD",
                    }[scope.market]
                ):
                    continue
                bar = latest_bar(db, position.symbol, scope, today())
                reasons = []
                observed = position.observed_at or snap.as_of
                stale = observed.tzinfo is None or not timedelta(
                    minutes=-1
                ) <= now() - observed <= timedelta(hours=24)
                if stale:
                    reasons.append(
                        "持仓需要更新：记录已超过 24 小时或时间异常。"
                        "请同步券商，或告诉 Agent 现在是否仍持有、股数、成本和确认时间"
                    )
                adjustment_label = {
                    "forward": "前复权",
                    "backward": "后复权",
                    "none": "不复权",
                }[scope.adjustment]
                if bar is None:
                    reasons.append(
                        f"缺这只股票的行情（{position.symbol} · {scope.source} · {adjustment_label}）："
                        "可让 Agent 补这只股票在该来源、复权方式下的已收盘日线；刷新页面不会采集行情"
                    )
                elif today() - bar.trade_date > timedelta(days=4):
                    reasons.append(
                        f"行情距今超过 4 个自然日（最近：{bar.trade_date} · {scope.source}）："
                        "需补该股票同源、同复权的近期已收盘日线，当前仅供历史复核"
                    )
                orders = [
                    o
                    for o in snap.orders
                    if o.symbol == position.symbol
                    and o.side == "sell"
                    and o.status not in {"cancelled", "expired", "filled"}
                ]
                exits = []
                for order in orders:
                    threshold = order.trigger_price
                    if (
                        threshold is None
                        or bar is None
                        or order.order_kind not in {"stop_loss", "take_profit"}
                    ):
                        continue
                    crossed = (
                        bar.close <= threshold
                        if order.order_kind == "stop_loss"
                        else bar.close >= threshold
                    )
                    if crossed:
                        exits.append("止损" if order.order_kind == "stop_loss" else "止盈")
                        reasons.append(
                            f"{bar.trade_date} 同源收盘 {bar.close} {position.currency} 达到已记录{exits[-1]} {threshold}；证据：{order.evidence}"
                        )
                if not orders:
                    reasons.append(
                        "缺退出计划：没有已记录的卖出计划或条件单。"
                        "请提供止损价、止盈价或退出条件，以及各卖多少股/多少比例；尚未决定就保留待补充"
                    )
                covered = sum(
                    (
                        o.quantity or Decimal(0)
                        for o in orders
                        if o.order_kind in {"stop_loss", "trailing"}
                        and o.status == "active"
                        and o.evidence == "broker_verified"
                        and o.quantity is not None
                        and o.observed_at is not None
                        and o.observed_at.tzinfo is not None
                        and timedelta(minutes=-1) <= now() - o.observed_at <= timedelta(hours=24)
                    ),
                    Decimal(0),
                )
                missing_protection = covered < position.quantity
                if missing_protection:
                    reasons.append(
                        "券商止损单尚未核验完整："
                        f"系统仅核验到 {covered} / {position.quantity} 股的有效止损覆盖。"
                        "请同步券商确认止损单类型、有效状态、数量和更新时间；"
                        "无接口账户可口述实际挂单情况，标为人工确认，仍不冒充券商核验。只填计划价格不算已挂单"
                    )
                signal = latest_signal(db, position.symbol, scope, today())
                result.append(
                    {
                        "account_label": account.label,
                        "symbol": position.symbol,
                        "name": position.name,
                        "currency": position.currency,
                        "snapshot_id": row.id,
                        "observed_at": observed.isoformat(),
                        "close": str(bar.close) if bar else None,
                        "price_date": str(bar.trade_date) if bar else None,
                        "decision": "needs_input"
                        if stale
                        or missing_protection
                        or bar is None
                        or not orders
                        or (bar and today() - bar.trade_date > timedelta(days=4))
                        else "review_exit"
                        if exits
                        else "observe",
                        "reasons": reasons
                        or ["本次缓存观察未触及已记录的止盈止损；结合研究继续复核"],
                        "strategies": signal.hits if signal else [],
                    }
                )
    return result


def overview(scope: Scope, target: date | None = None) -> dict:
    from tradeguard.research.recommendations import latest

    target = bounded_day(target)
    with session() as db:
        summary = db.scalar(
            select(ScanSummary)
            .where(
                ScanSummary.market == scope.market,
                ScanSummary.source == scope.source,
                ScanSummary.adjustment == scope.adjustment,
                ScanSummary.trade_date <= target,
            )
            .order_by(ScanSummary.trade_date.desc())
            .limit(1)
        )
        report = (
            daily_report(summary.trade_date, scope.market, scope.source, scope.adjustment)
            if summary
            else None
        )
        profiles = [
            {"id": r.id, "name": r.name, "created_at": r.created_at.isoformat(), "rules": r.rules}
            for r in db.scalars(select(RuleProfile).order_by(RuleProfile.created_at.desc())).all()
        ]
        checks = [
            {
                "id": c.id,
                "created_at": c.created_at.isoformat(),
                "symbol": c.intent.get("symbol"),
                "rule_profile_id": c.rule_profile_id,
                "snapshot_id": c.snapshot_id,
                "result": c.result,
            }
            for c in db.scalars(
                select(DisciplineCheck).order_by(DisciplineCheck.created_at.desc()).limit(20)
            ).all()
            if currency_for(c.intent["symbol"])
            == {"CN": "CNY", "US": "USD", "HK": "HKD"}[scope.market]
        ]
    return {
        "scope": scope.model_dump(),
        "as_of": now().isoformat(),
        "report": report,
        "recommendation": latest(scope, target),
        "watchlist": watches(scope, target),
        "position_reviews": position_reviews(scope),
        "notifications": inbox(scope),
        "profiles": profiles,
        "recent_checks": checks,
    }
