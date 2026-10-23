"""Loopback-only HTTP adapter for the copied selection frontend."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from tradeguard.db import session
from tradeguard.db.models import (
    DailyBar,
    Run,
    RunEvent,
    ScanResult,
    Security,
    now,
)
from tradeguard.market.schemas import normalize_symbol
from tradeguard.portfolio.schemas import ManualPatch
from tradeguard.portfolio.service import create_account, manual_update
from tradeguard.screening.availability import (
    bounded_day,
    cached_dates,
    has_cached_equities,
    preferred_source,
    source_activity,
    today,
)
from tradeguard.screening.filters import FilterOptions
from tradeguard.screening.service import create_run, scan
from tradeguard.workspace import service as workspace
from tradeguard.workspace.schemas import AlertInput, Scope, WatchInput

MARKETS = {"CN": ("A 股", "CNY"), "US": ("美股", "USD"), "HK": ("港股", "HKD")}
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tradeguard-scan")


def ensure_market(market):
    if market not in MARKETS:
        raise HTTPException(422, "选择 A 股、美股或港股")
    return market


def context_data(market):
    ensure_market(market)
    with session() as db:
        securities = db.scalar(
            select(func.count()).select_from(Security).where(Security.market == market)
        )
        rows = db.execute(
            select(
                DailyBar.source,
                DailyBar.adjustment,
                func.count(),
                func.count(func.distinct(DailyBar.symbol)),
                func.min(DailyBar.trade_date),
                func.max(DailyBar.trade_date),
            )
            .join(Security, Security.symbol == DailyBar.symbol)
            .where(Security.market == market, DailyBar.trade_date <= today())
            .group_by(DailyBar.source, DailyBar.adjustment)
            .with_hint(DailyBar, "FORCE INDEX (ix_daily_bar_source_adjustment_date)", "mysql")
        ).all()
        activity = source_activity(db, market)
    sources = [
        {
            "source": s,
            "adjustment": a,
            "rows": n,
            "symbols": sy,
            "min_date": str(mi),
            "max_date": str(ma),
            **activity.get((s, a), {"scan_count": 0, "latest_scan_date": None}),
        }
        for s, a, n, sy, mi, ma in rows
    ]
    preferred = preferred_source(sources)
    return {
        "market": market,
        "label": MARKETS[market][0],
        "currency": MARKETS[market][1],
        "security_count": securities,
        "sources": sources,
        "default_source": preferred["source"] if preferred else "",
        "default_adjustment": preferred["adjustment"] if preferred else "forward",
        "max_date": preferred["max_date"] if preferred else None,
        "filter_defaults": FilterOptions.for_market(market).model_dump(),
    }


def source_for(market, source):
    if source:
        return source
    return context_data(market)["default_source"]


def scan_query(market: str, source: str = "", adjustment: str = "forward"):
    ensure_market(market)
    query = select(Run).where(
        Run.kind == "scan",
        Run.market == market,
        func.coalesce(Run.details["adjustment"].as_string(), "forward") == adjustment,
    )
    if source:
        query = query.where(Run.details["source"].as_string() == source)
    return query


def get_run(db, identifier, market, source="", adjustment="forward"):
    ensure_market(market)
    run = db.get(Run, identifier)
    if run is None:
        try:
            day = date.fromisoformat(identifier)
        except ValueError:
            raise HTTPException(404, "扫描批次不存在") from None
        run = db.scalar(
            scan_query(market, source, adjustment)
            .where(Run.market_date == day)
            .order_by(Run.started_at.desc())
            .limit(1)
        )
    if (
        run is None
        or run.kind != "scan"
        or run.market != market
        or (source and run.details.get("source") != source)
        or run.details.get("adjustment", "forward") != adjustment
    ):
        raise HTTPException(404, "该市场没有这个扫描批次")
    return run


def result_rows(db, run):
    rows = db.execute(
        select(ScanResult, Security)
        .join(Security, Security.symbol == ScanResult.symbol)
        .where(ScanResult.run_id == run.id)
    ).all()
    return [
        {
            "id": run.id + ":" + r.symbol,
            "stockCode": r.symbol,
            "stockName": (r.metadata_snapshot or {}).get("name") or s.name,
            "industry": (r.metadata_snapshot or {}).get("industry") or s.industry,
            "scanDate": str(r.trade_date),
            "resonanceCount": len(r.hits),
            "strategiesHit": r.hits,
            "sectorStrength": (r.metadata_snapshot or {}).get("sector_strength"),
            "latestPrice": float(r.close),
            "currency": s.currency,
        }
        for r, s in rows
    ]


def summary(run, rows):
    d = run.details
    groups = Counter(r["industry"] or "未知" for r in rows)
    totals = d.get("universe", 0)
    skipped = d.get("skipped", [])
    duration = ((run.finished_at or now()) - run.started_at).total_seconds()
    options = d.get("filter_options", {})
    return {
        "id": run.id,
        "scanDate": str(run.market_date or d.get("date", "")),
        "market": run.market,
        "source": d.get("source"),
        "status": run.status,
        "executionDate": run.started_at.isoformat(),
        "executionTime": duration,
        "tradableCount": d.get("scanned_count", totals - len(skipped)),
        "candidateCount": d.get("resonance_count", sum(r["resonanceCount"] >= 2 for r in rows)),
        "hitStockCount": len(rows),
        "hitIndustryCount": len(groups),
        "sectorCount": sum(v > 0 for v in d.get("sector_strength", {}).values()),
        "resonanceIndustryCount": sum(
            sum(r["resonanceCount"] >= 2 for r in rows if (r["industry"] or "未知") == ind) >= 2
            for ind in groups
        ),
        "topSectors": [
            {"sector": name, "rs": d.get("sector_strength", {}).get(name), "count": count}
            for name, count in groups.most_common(8)
        ],
        "marketRegime": d.get("market_regime", "unknown"),
        "totalStockCount": totals,
        "filteredOutCount": len(skipped),
        "scannedStockCount": d.get("scanned_count", totals - len(skipped)),
        "scanStrategies": d.get("strategies", []),
        "strategyHitCounts": d.get("strategy_hit_counts", {}),
        "filterCounts": d.get("filter_counts", dict(Counter(s["reason"] for s in skipped))),
        "warnings": d.get("warnings", {}),
        "error": d.get("error"),
        "found": True,
        "filterConfig": {
            "filterSt": options.get("filter_st", False),
            "filterNewStock": options.get("filter_new_stock", False),
            "filterLiquidity": options.get("filter_liquidity", False),
            "filterSuspended": options.get("filter_suspended", False),
            "filterLimit": options.get("filter_limit", False),
            "minAvgVolume5d": options.get("min_avg_amount"),
            "minListedDays": options.get("min_listed_days"),
            "limitPct": options.get("limit_pct"),
        },
    }


def safe_worker(run_id, payload):
    try:
        scan(
            payload.date,
            payload.source,
            payload.adjustment,
            market=payload.market,
            filters=payload.filters,
            symbols=payload.symbols,
            run_id=run_id,
        )
    except Exception:
        pass  # scan() already commits the failure and a visible terminal event.


def stock_signals(
    symbol: str,
    market: str = "CN",
    source: str = "",
    limit: int = 180,
    adjustment: str = "forward",
    target: date | None = None,
) -> list[dict]:
    symbol = normalize_symbol(symbol)
    ensure_market(market)
    chosen = source_for(market, source)
    target = bounded_day(target)
    with session() as db:
        security = db.get(Security, symbol)
        if security is None or security.market != market:
            raise HTTPException(404, "标的不存在于当前市场")
        rows = db.execute(
            select(ScanResult, Run)
            .join(Run, Run.id == ScanResult.run_id)
            .where(
                ScanResult.symbol == symbol,
                Run.market == market,
                Run.kind == "scan",
                Run.details["source"].as_string() == chosen,
                func.coalesce(Run.details["adjustment"].as_string(), "forward") == adjustment,
                ScanResult.trade_date <= target,
            )
            .order_by(ScanResult.trade_date.desc(), Run.started_at.desc())
            .limit(max(1, min(limit, 500)) * 3)
        ).all()
    seen: set[date] = set()
    payload = []
    for result, run in rows:
        if chosen and (run.details or {}).get("source") != chosen:
            continue
        if result.trade_date in seen:
            continue
        seen.add(result.trade_date)
        snap = result.metadata_snapshot or {}
        payload.append(
            {
                "date": str(result.trade_date),
                "strategies": result.hits,
                "resonanceCount": result.resonance_count or len(result.hits or []),
                "reasons": [
                    item.get("reason") or item.get("title") or item.get("strategy")
                    for item in (snap.get("strategy_details") or [])
                    if isinstance(item, dict)
                ],
            }
        )
        if len(payload) >= limit:
            break
    return list(reversed(payload))


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str
    date: date
    source: str
    adjustment: Literal["forward", "none", "backward"] = "forward"
    symbols: list[str] | None = None
    filters: dict | None = None


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    broker: str
    label: str


class CheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str
    intent: dict


def create_app():
    app = FastAPI(title="TradeGuard local console")

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed = {
                "http://127.0.0.1:5178",
                "http://localhost:5178",
                "http://127.0.0.1:8188",
                "http://localhost:8188",
            }
            # A local deployment may select another port. Allow its own origin,
            # while retaining the loopback boundary and the explicit dev proxy.
            if request.url.hostname in {"127.0.0.1", "localhost", "::1"}:
                allowed.add(str(request.base_url).rstrip("/"))
            if origin and origin not in allowed:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "请从本机控制台操作"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "数据库操作失败，请检查 MySQL 和迁移状态"}, status_code=503)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/context")
    def context(market: str = "CN"):
        return context_data(market)

    @app.get("/api/workspace")
    def workspace_overview(
        market: str, source: str, adjustment: str = "forward", target: date | None = None
    ):
        return workspace.overview(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment}),
            target,
        )

    @app.get("/api/search")
    def search_stocks(market: str, source: str, q: str = "", adjustment: str = "forward"):
        return workspace.search(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment}), q
        )

    @app.get("/api/watchlist")
    def watchlist(market: str, source: str, adjustment: str = "forward"):
        return workspace.watches(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment})
        )

    @app.post("/api/watchlist")
    def watch_add(payload: WatchInput):
        return workspace.add_watch(payload)

    @app.delete("/api/watchlist/{identifier}")
    def watch_remove(identifier: str):
        return workspace.remove_watch(identifier)

    @app.get("/api/alerts")
    def alert_list(market: str, source: str, adjustment: str = "forward"):
        return workspace.alerts(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment})
        )

    @app.post("/api/alerts")
    def alert_add(payload: AlertInput):
        return workspace.add_alert(payload)

    @app.delete("/api/alerts/{identifier}")
    def alert_cancel(identifier: str):
        return workspace.cancel_alert(identifier)

    @app.get("/api/notifications")
    def notification_list(market: str, source: str, adjustment: str = "forward"):
        return workspace.inbox(
            Scope.model_validate({"market": market, "source": source, "adjustment": adjustment})
        )

    @app.post("/api/notifications/refresh")
    def notifications_refresh(payload: Scope):
        return workspace.refresh(payload)

    @app.post("/api/notifications/{identifier}/read")
    def notification_read(identifier: str):
        return workspace.mark_read(identifier)

    @app.post("/api/discipline/check")
    def check_trade(payload: CheckInput):
        from tradeguard.discipline.schemas import Intent
        from tradeguard.discipline.service import check

        return check(Intent.model_validate(payload.intent), payload.profile_id)

    @app.get("/api/health")
    def health():
        with session() as db:
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        return {"database": "mysql", "migration": revision, "status": "ok"}

    @app.get("/api/scan/summaries")
    def scan_summaries(market: str = "CN", source: str = "", adjustment: str = "forward"):
        ensure_market(market)
        with session() as db:
            runs = db.scalars(
                scan_query(market, source, adjustment).order_by(Run.started_at.desc()).limit(200)
            ).all()
            return [summary(run, result_rows(db, run)) for run in runs]

    @app.get("/api/scan/dates")
    def scan_dates(market: str, source: str = "", adjustment: str = "forward"):
        ensure_market(market)
        if adjustment not in {"forward", "none", "backward"}:
            raise HTTPException(422, "请选择有效的复权方式")
        return cached_dates(market, source, adjustment)

    @app.post("/api/scan/run")
    def launch(payload: ScanInput):
        bounded_day(payload.date)
        ensure_market(payload.market)
        FilterOptions.for_market(payload.market, payload.filters)
        if not payload.source:
            raise HTTPException(422, "该市场尚未导入行情，请先通过 CLI 更新数据")
        if payload.symbols:
            payload.symbols = [normalize_symbol(s) for s in payload.symbols]
        if not has_cached_equities(
            payload.date, payload.market, payload.source, payload.adjustment, payload.symbols
        ):
            raise HTTPException(
                422, "所选市场、来源和复权在该交易日没有可扫描的股票缓存，请选择有缓存的日期"
            )
        run_id = create_run(
            payload.date, payload.market, payload.source, payload.filters, payload.adjustment
        )
        EXECUTOR.submit(safe_worker, run_id, payload)
        return {"run_id": run_id, "status": "queued"}

    @app.get("/api/scan/{identifier}/summary")
    def scan_summary(
        identifier: str, market: str = "CN", source: str = "", adjustment: str = "forward"
    ):
        with session() as db:
            run = get_run(db, identifier, market, source, adjustment)
            return summary(run, result_rows(db, run))

    @app.get("/api/scan/{identifier}/results")
    def scan_results(
        identifier: str,
        market: str = "CN",
        min_resonance: int = 1,
        industry: str | None = None,
        source: str = "",
        adjustment: str = "forward",
    ):
        with session() as db:
            run = get_run(db, identifier, market, source, adjustment)
            return [
                r
                for r in result_rows(db, run)
                if r["resonanceCount"] >= min_resonance
                and (industry is None or r["industry"] == industry)
            ]

    @app.get("/api/scan/{identifier}/events")
    def events(identifier: str, market: str = "CN", source: str = "", adjustment: str = "forward"):
        with session() as db:
            run = get_run(db, identifier, market, source, adjustment)
            rows = db.scalars(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)
            ).all()
            return {
                "run_id": run.id,
                "status": run.status,
                "skipped": run.details.get("skipped", []),
                "events": [
                    {
                        "id": e.id,
                        "at": e.created_at.isoformat(),
                        "stage": e.stage,
                        "message": e.message,
                        "completed": e.completed,
                        "total": e.total,
                    }
                    for e in rows
                ],
            }

    @app.get("/api/scan/{identifier}/sectors")
    def sectors(identifier: str, market: str = "CN", source: str = "", adjustment: str = "forward"):
        with session() as db:
            run = get_run(db, identifier, market, source, adjustment)
            groups = defaultdict(list)
            for r in result_rows(db, run):
                groups[r["industry"] or "未知"].append(r)
            return [
                {
                    "industry": industry,
                    "candidateCount": len(stocks),
                    "rsScore": run.details.get("sector_strength", {}).get(industry),
                    "stocks": stocks,
                }
                for industry, stocks in sorted(
                    groups.items(), key=lambda x: len(x[1]), reverse=True
                )
            ]

    @app.get("/api/kline/{symbol}")
    def kline(
        symbol: str,
        market: str = "CN",
        source: str = "",
        days: int = 120,
        endDate: date | None = None,
        adjustment: str = "forward",
    ):
        symbol = normalize_symbol(symbol)
        with session() as db:
            security = db.get(Security, symbol)
            if security is None or security.market != market:
                raise HTTPException(404, "该市场没有此标的")
            src = source_for(market, source)
            query = select(DailyBar).where(
                DailyBar.symbol == symbol,
                DailyBar.source == src,
                DailyBar.adjustment == adjustment,
                DailyBar.trade_date <= bounded_day(endDate),
            )
            if endDate:
                query = query.where(DailyBar.trade_date <= endDate)
            bars = db.scalars(
                query.order_by(DailyBar.trade_date.desc()).limit(max(1, min(days, 2000)))
            ).all()[::-1]
        if not bars:
            return []
        frame = pd.DataFrame(
            [
                {k: float(getattr(b, k)) for k in ["open", "high", "low", "close", "volume"]}
                for b in bars
            ]
        )
        for n in [5, 10, 20, 60]:
            frame[f"ma{n}"] = frame.close.rolling(n).mean()
        frame["bb_middle"] = frame.close.rolling(20).mean()
        frame["bb_upper"] = frame.bb_middle + 2 * frame.close.rolling(20).std()
        frame["bb_lower"] = frame.bb_middle - 2 * frame.close.rolling(20).std()
        records = frame.astype(object).where(pd.notnull(frame), None).to_dict(orient="records")
        return [
            {
                **r,
                "date": str(b.trade_date),
                "amount": float(b.amount) if b.amount is not None else None,
            }
            for r, b in zip(records, bars, strict=True)
        ]

    @app.get("/api/stocks/{symbol}/profile")
    def profile(
        symbol: str,
        market: str = "CN",
        source: str = "",
        adjustment: str = "forward",
        endDate: date | None = None,
    ):
        symbol = normalize_symbol(symbol)
        with session() as db:
            s = db.get(Security, symbol)
            if s is None or s.market != market:
                raise HTTPException(404, "标的不存在于当前市场")
            bars = kline(symbol, market, source, 1, endDate, adjustment)
            latest_bar = bars[-1] if bars else {}
            signals = stock_signals(
                symbol, market, source, limit=1, adjustment=adjustment, target=endDate
            )
            latest_signal = signals[-1] if signals else {}
            return {
                "code": s.symbol,
                "name": s.name,
                "market": s.market,
                "currency": s.currency,
                "industry": s.sector or s.industry,
                "sector": s.sector,
                "isSt": bool(s.is_st),
                "listDate": str(s.list_date) if s.list_date else None,
                "category": s.security_kind,
                "lastDataDate": latest_bar.get("date"),
                "dataDays": db.scalar(
                    select(func.count())
                    .select_from(DailyBar)
                    .where(
                        DailyBar.symbol == symbol,
                        DailyBar.source == source_for(market, source),
                        DailyBar.adjustment == adjustment,
                        DailyBar.trade_date <= bounded_day(endDate),
                    )
                ),
                "latestQuote": latest_bar,
                "latestScan": {
                    "strategiesHit": latest_signal.get("strategies", []),
                    "scanDate": latest_signal.get("date"),
                    "resonanceCount": latest_signal.get("resonanceCount"),
                    "reasons": latest_signal.get("reasons", []),
                },
            }

    @app.get("/api/stocks/{symbol}/signals")
    def signals(
        symbol: str,
        market: str = "CN",
        source: str = "",
        limit: int = 180,
        adjustment: str = "forward",
        endDate: date | None = None,
    ):
        return stock_signals(symbol, market, source, limit, adjustment, endDate)

    @app.get("/api/portfolio/accounts")
    def portfolio_accounts():
        from tradeguard.portfolio.view import accounts_view

        return accounts_view()

    @app.post("/api/portfolio/accounts")
    def add_account(payload: AccountInput):
        return create_account(payload.account_id, payload.broker, payload.label)

    @app.post("/api/portfolio/accounts/{account_id}/update")
    def update_account(account_id: str, payload: ManualPatch):
        return manual_update(account_id, payload)

    @app.post("/api/portfolio/sync/{account_id}")
    def sync_account(account_id: str):
        from tradeguard.portfolio.view import sync_account_view

        return sync_account_view(account_id)

    @app.get("/api/stock-pool/filter")
    def filtered_pool(
        market: str = "CN",
        source: str = "",
        target_date: date | None = None,
        filter_st: bool = True,
        filter_new_stock: bool = True,
        filter_liquidity: bool = True,
        filter_market_cap: bool = False,
        filter_suspended: bool = True,
        filter_limit: bool = True,
        min_avg_volume: float | None = None,
        min_listed_days: int | None = None,
        limit_pct: float = 0.095,
        adjustment: Literal["forward", "none", "backward"] = "forward",
    ):
        from tradeguard.screening.pool import filter_pool

        if filter_market_cap:
            raise HTTPException(422, "当前缓存没有可靠市值数据，请关闭市值过滤")
        return filter_pool(
            market,
            source_for(market, source),
            target_date,
            {
                **FilterOptions.for_market(market).model_dump(),
                "filter_st": filter_st if market == "CN" else False,
                "filter_new_stock": filter_new_stock,
                "filter_liquidity": filter_liquidity,
                "filter_suspended": filter_suspended,
                "filter_limit": filter_limit if market == "CN" else False,
                "min_avg_amount": min_avg_volume
                if min_avg_volume is not None
                else FilterOptions.for_market(market).min_avg_amount,
                "min_listed_days": min_listed_days
                if min_listed_days is not None
                else FilterOptions.for_market(market).min_listed_days,
                "limit_pct": limit_pct,
            },
            adjustment,
        )

    web = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web.exists():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(web / "index.html")

    return app
