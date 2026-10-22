import hashlib
import inspect
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.locks import named_lock
from tradeguard.db.maintenance import retire_stale_runs
from tradeguard.db.models import (
    DailyBar,
    Run,
    RunEvent,
    ScanResult,
    ScanSummary,
    Security,
    now,
    uid,
)
from tradeguard.db.write import upsert
from tradeguard.screening import indicators
from tradeguard.screening.filters import FilterOptions, rejection
from tradeguard.screening.strategies.registry import get_registered_strategies

DEFAULT_STRATEGIES = [
    "ma_golden_cross",
    "macd_golden_cross",
    "rsi_rebound",
    "bollinger_breakout",
    "box_breakout",
]


def event(
    run_id: str, stage: str, message: str, completed: int | None = None, total: int | None = None
):
    with session() as db, db.begin():
        db.add(
            RunEvent(run_id=run_id, stage=stage, message=message, completed=completed, total=total)
        )


def create_run(target: date, market: str, source: str, filters: dict | None = None):
    if market not in {"CN", "US", "HK"}:
        raise ValueError("Market must be CN, US or HK")
    with session() as db, db.begin():
        run = Run(
            kind="scan",
            market=market,
            market_date=target,
            status="queued",
            details={
                "date": str(target),
                "market": market,
                "source": source,
                "filter_options": filters or {},
            },
        )
        db.add(run)
        db.flush()
        return run.id


def scan(
    target: date,
    source: str,
    adjustment: str = "forward",
    symbols: list[str] | None = None,
    min_resonance: int = 1,
    market: str = "CN",
    filters: dict | None = None,
    run_id: str | None = None,
) -> dict:
    if min_resonance < 1:
        raise ValueError("min_resonance must be positive")
    options = FilterOptions.for_market(market, filters)
    retire_stale_runs()
    run_id = run_id or create_run(target, market, source, filters)
    try:
        with named_lock(f"scan:{market}"):
            return _scan(
                target, source, adjustment, symbols, min_resonance, market, options, run_id
            )
    except Exception as exc:
        with session() as db, db.begin():
            run = db.get(Run, run_id)
            if run:
                run.status, run.finished_at = "failed", now()
                run.details = {
                    **run.details,
                    "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                }
        event(run_id, "failed", "扫描未完成；错误已保留，未标记为成功。")
        raise


def _scan(target, source, adjustment, symbols, min_resonance, market, options, run_id):
    strategies = get_registered_strategies(DEFAULT_STRATEGIES)
    modules = [inspect.getmodule(s.__class__) for s in strategies]
    version = hashlib.sha256(
        (
            inspect.getsource(indicators) + "".join(inspect.getsource(m) for m in modules if m)
        ).encode()
    ).hexdigest()
    with session() as db, db.begin():
        run = db.get(Run, run_id)
        if run is None or run.kind != "scan" or run.market != market:
            raise ValueError("Scan run mismatch")
        run.status = "running"
        query = (
            select(Security)
            .where(Security.market == market, Security.security_kind != "index")
            .order_by(Security.symbol)
        )
        if symbols:
            query = query.where(Security.symbol.in_(symbols))
        securities = db.scalars(query).all()
        if symbols and set(symbols) != {s.symbol for s in securities}:
            raise ValueError("Requested symbols must exist in the selected market")
    if not securities:
        raise ValueError(
            "No securities stored for this market; import data or configure a universe first"
        )
    event(
        run_id,
        "universe",
        f"载入 {market} 股票池，共 {len(securities)} 个标的；数据源 {source}。",
        0,
        len(securities),
    )
    benchmark = "000001.SH" if market == "CN" else "SPY.US" if market == "US" else "02800.HK"
    with session() as db:
        index = db.scalars(
            select(DailyBar)
            .where(
                DailyBar.symbol == benchmark,
                DailyBar.source == source,
                DailyBar.adjustment == adjustment,
                DailyBar.trade_date <= target,
            )
            .order_by(DailyBar.trade_date.desc())
            .limit(30)
        ).all()[::-1]
    regime, index_return = "unknown", None
    if len(index) >= 25 and index[-1].trade_date == target:
        closes = pd.Series([float(b.close) for b in index])
        ma = closes.rolling(20).mean()
        regime = (
            "bull"
            if closes.iloc[-1] > ma.iloc[-1] and ma.iloc[-1] > ma.iloc[-5]
            else "bear"
            if closes.iloc[-1] < ma.iloc[-1] and ma.iloc[-1] < ma.iloc[-5]
            else "neutral"
        )
        index_return = float(index[-1].close / index[-20].close - 1)
    event(
        run_id,
        "market",
        f"基准 {benchmark}："
        + ("数据不足，市场环境未判断。" if regime == "unknown" else f"市场状态 {regime}。"),
    )
    event(
        run_id,
        "filter",
        "按所选市场的 ST、停牌、上市时间、流动性与涨跌幅规则初筛；美股不套用 A 股涨跌停。",
    )
    digest = hashlib.sha256(
        json.dumps(
            {
                "date": str(target),
                "source": source,
                "market": market,
                "adjustment": adjustment,
                "filter_options": options.model_dump(),
            },
            sort_keys=True,
        ).encode()
    )
    skipped, candidates = [], []
    warnings: Counter = Counter()
    hit_counts: Counter = Counter()
    sector_samples = defaultdict(list)
    scanned = 0
    fields = ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]
    for offset in range(0, len(securities), 64):
        batch = securities[offset : offset + 64]
        with session() as db:
            rows = (
                db.execute(
                    select(*(getattr(DailyBar, k) for k in fields))
                    .where(
                        DailyBar.symbol.in_([s.symbol for s in batch]),
                        DailyBar.trade_date <= target,
                        DailyBar.source == source,
                        DailyBar.adjustment == adjustment,
                    )
                    .order_by(DailyBar.symbol, DailyBar.trade_date)
                )
                .mappings()
                .all()
            )
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["symbol"]].append(dict(row))
        for security in batch:
            bars = grouped[security.symbol][-400:]
            reason, notices = rejection(security, bars, target, market, options)
            warnings.update(notices)
            if reason:
                skipped.append({"symbol": security.symbol, "reason": reason})
                continue
            scanned += 1
            sector_name = security.sector or security.industry
            data = [
                {
                    "date": str(b["trade_date"]),
                    **{k: float(b[k]) for k in ["open", "high", "low", "close", "volume"]},
                }
                for b in bars
            ]
            digest.update(
                json.dumps(
                    [security.symbol, security.name, sector_name, data], sort_keys=True
                ).encode()
            )
            frame = pd.DataFrame(data)
            hit_details = []
            for strategy in strategies:
                found = strategy.screen(
                    stock_code=security.symbol,
                    stock_name=security.name,
                    df=frame.copy(),
                    result_date=str(target),
                    industry=sector_name or "未知",
                )
                if found:
                    hit_details.append(
                        {
                            "strategy": strategy.name,
                            "title": strategy.title,
                            "reason": strategy.description,
                            "metadata": found.get("metadata"),
                        }
                    )
            hits = [item["strategy"] for item in hit_details]
            hit_counts.update(hits)
            if len(bars) >= 60 and sector_name:
                amounts = [
                    float(b["amount"])
                    if b["amount"] is not None
                    else float(b["close"] * b["volume"])
                    for b in bars[-60:]
                ]
                energy = (
                    (sum(amounts[-5:]) / 5) / (sum(amounts) / len(amounts)) - 1
                    if sum(amounts) > 0
                    else None
                )
                pct = float(bars[-1]["close"] / bars[-20]["close"] - 1)
                sector_samples[sector_name].append((pct, energy))
            if hits:
                candidates.append(
                    {
                        "symbol": security.symbol,
                        "name": security.name,
                        "hits": hits,
                        "strategy_details": hit_details,
                        "close": str(bars[-1]["close"]),
                        "industry": sector_name,
                        "sector": security.sector or sector_name,
                        "market": market,
                        "currency": security.currency,
                    }
                )
        event(
            run_id,
            "strategies",
            f"已处理 {min(offset + len(batch), len(securities))}/{len(securities)} 个标的，{scanned} 个进入五策略计算。",
            min(offset + len(batch), len(securities)),
            len(securities),
        )
    sectors = Counter(c["sector"] or c["industry"] or "未知" for c in candidates)
    rs = {}
    if index_return is not None:
        for industry, values in sector_samples.items():
            valid = [(p, e) for p, e in values if e is not None]
            if valid:
                rs[industry] = round(sum(p + e for p, e in valid) / len(valid) - index_return, 6)
    event(
        run_id,
        "sectors",
        f"汇总 {len(sectors)} 个命中行业；"
        + (
            "基准缺失，相对强度保留未知。"
            if index_return is None
            else "按行业涨幅、成交能量与基准计算强度。"
        ),
    )
    config = options.model_dump()
    details = {
        "date": str(target),
        "market": market,
        "source": source,
        "adjustment": adjustment,
        "universe": len(securities),
        "scanned_count": scanned,
        "skipped": skipped,
        "filter_counts": dict(Counter(s["reason"] for s in skipped)),
        "warnings": dict(warnings),
        "candidate_count": sum(len(c["hits"]) >= min_resonance for c in candidates),
        "hit_stock_count": len(candidates),
        "resonance_count": sum(len(c["hits"]) >= 2 for c in candidates),
        "sector_counts": dict(sectors),
        "sector_strength": rs,
        "market_regime": regime,
        "benchmark": benchmark,
        "strategy_version": version,
        "strategies": DEFAULT_STRATEGIES,
        "strategy_hit_counts": dict(hit_counts),
        "input_hash": digest.hexdigest(),
        "min_resonance": min_resonance,
        "filter_options": config,
    }
    incomplete = any(s["reason"] in {"missing_target_bar", "insufficient_history"} for s in skipped)
    with session() as db, db.begin():
        run = db.get(Run, run_id)
        assert run is not None
        for c in candidates:
            sector_key = c["sector"] or c["industry"]
            strength = rs.get(sector_key)
            metadata = {
                "name": c["name"],
                "industry": c["industry"],
                "sector": c["sector"],
                "market": c["market"],
                "currency": c["currency"],
                "sector_strength": strength,
                "resonance_count": len(c["hits"]),
                "strategy_details": c["strategy_details"],
            }
            db.add(
                ScanResult(
                    run_id=run_id,
                    symbol=c["symbol"],
                    trade_date=target,
                    hits=c["hits"],
                    close=c["close"],
                    resonance_count=len(c["hits"]),
                    sector_strength=None if strength is None else Decimal(str(strength)),
                    metadata_snapshot=metadata,
                )
            )
        status = "partial" if incomplete else "success"
        summary = {
            "id": uid(),
            "run_id": run_id,
            "market": market,
            "trade_date": target,
            "source": source,
            "adjustment": adjustment,
            "status": status,
            "market_regime": regime,
            "benchmark": benchmark,
            "universe_count": len(securities),
            "scanned_count": scanned,
            "hit_count": len(candidates),
            "resonance_count": sum(len(c["hits"]) >= 2 for c in candidates),
            "strategy_hit_counts": dict(hit_counts),
            "sector_strength": rs,
            "filter_counts": dict(Counter(s["reason"] for s in skipped)),
            "created_at": now(),
            "updated_at": now(),
        }
        db.execute(
            upsert(
                ScanSummary,
                [summary],
                [
                    "run_id",
                    "status",
                    "market_regime",
                    "benchmark",
                    "universe_count",
                    "scanned_count",
                    "hit_count",
                    "resonance_count",
                    "strategy_hit_counts",
                    "sector_strength",
                    "filter_counts",
                    "updated_at",
                ],
            )
        )
        run.status, run.finished_at, run.details = (status, now(), details)
    event(
        run_id,
        "complete",
        f"已保存扫描批次：{len(candidates)} 个命中，{len(skipped)} 个过滤或缺数据；每条原因均可查看。",
        len(securities),
        len(securities),
    )
    return {
        "run_id": run_id,
        "status": "partial" if incomplete else "success",
        **details,
        "candidates": [c for c in candidates if len(c["hits"]) >= min_resonance],
    }


def results(run_id: str, market: str | None = None) -> dict:
    with session() as db:
        run = db.get(Run, run_id)
        if run is None or run.kind != "scan" or (market and run.market != market):
            raise ValueError("Scan run not found in this market")
        rows = db.scalars(select(ScanResult).where(ScanResult.run_id == run_id)).all()
        return {
            "run_id": run.id,
            "status": run.status,
            **run.details,
            "candidates": [
                {
                    "symbol": r.symbol,
                    "hits": r.hits,
                    "close": str(r.close),
                    **(r.metadata_snapshot or {}),
                }
                for r in rows
            ],
        }
