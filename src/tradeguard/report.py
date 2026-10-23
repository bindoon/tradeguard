"""Machine-readable daily scan report for an agent to summarize."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import ScanResult, ScanSummary


def _reasons(snapshot: dict[str, Any] | None) -> list[str]:
    lines = []
    for item in (snapshot or {}).get("strategy_details") or []:
        title = str(item.get("title") or item.get("strategy") or "")
        reason = str(item.get("reason") or "")
        meta = item.get("metadata") or {}
        bits = []
        if isinstance(meta, dict):
            for key, value in meta.items():
                if isinstance(value, dict):
                    continue
                bits.append(f"{key}={value}")
                if len(bits) == 4:
                    break
        extra = "，".join(bits)
        text = "：".join(part for part in (title, reason, extra) if part)
        if text:
            lines.append(text)
    return lines


def _pick(row: ScanResult) -> dict[str, Any]:
    snap = row.metadata_snapshot or {}
    strength = row.sector_strength
    if strength is None:
        strength = snap.get("sector_strength")
    return {
        "symbol": row.symbol,
        "name": snap.get("name"),
        "sector": snap.get("sector") or snap.get("industry"),
        "industry": snap.get("industry"),
        "resonance_count": row.resonance_count or len(row.hits or []),
        "strategies_hit": list(row.hits or []),
        "reasons": _reasons(snap),
        "close": str(row.close),
        "sector_strength": None
        if strength is None
        else float(strength)
        if not isinstance(strength, float)
        else strength,
    }


def _ranking(summary: ScanSummary, rows: list[ScanResult]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        snap = row.metadata_snapshot or {}
        sector = str(snap.get("sector") or snap.get("industry") or "未知")
        counts[sector] = counts.get(sector, 0) + 1
    strength = summary.sector_strength or {}
    names = set(counts) | set(strength)
    ranked = [
        {
            "sector": name,
            "strength": strength.get(name),
            "hit_count": counts.get(name, 0),
        }
        for name in names
    ]

    def sort_key(item: dict[str, Any]) -> tuple[float, int, str]:
        raw = item["strength"]
        score = float(raw) if isinstance(raw, int | float) else -999.0
        return (-score, -int(item["hit_count"]), str(item["sector"]))

    ranked.sort(key=sort_key)
    return ranked


def daily_report(
    target: date, market: str = "CN", source: str | None = None, adjustment: str = "forward"
) -> dict[str, Any]:
    if market not in {"CN", "US", "HK"}:
        raise ValueError("market must be CN, US or HK")
    with session() as db:
        query = select(ScanSummary).where(
            ScanSummary.market == market,
            ScanSummary.trade_date == target,
            ScanSummary.adjustment == adjustment,
        )
        if source:
            query = query.where(ScanSummary.source == source)
        summary = db.scalars(query.order_by(ScanSummary.updated_at.desc())).first()
        if summary is None:
            raise ValueError("No scan summary for this market date")
        rows = list(db.scalars(select(ScanResult).where(ScanResult.run_id == summary.run_id)).all())
        previous = db.scalars(
            select(ScanSummary)
            .where(
                ScanSummary.market == market,
                ScanSummary.source == summary.source,
                ScanSummary.adjustment == summary.adjustment,
                ScanSummary.trade_date < target,
            )
            .order_by(ScanSummary.trade_date.desc())
        ).first()
        previous_rows = []
        if previous is not None:
            previous_rows = list(
                db.scalars(select(ScanResult).where(ScanResult.run_id == previous.run_id)).all()
            )
    ranked_rows = sorted(
        rows, key=lambda row: (-(row.resonance_count or len(row.hits)), row.symbol)
    )
    resonant = [row for row in ranked_rows if (row.resonance_count or len(row.hits)) >= 2]
    picks = [_pick(row) for row in (resonant or ranked_rows)[:20]]
    current_symbols = {row.symbol: row for row in rows}
    previous_symbols = {row.symbol: row for row in previous_rows}
    new_symbols = [
        _pick(current_symbols[symbol])
        for symbol in sorted(set(current_symbols) - set(previous_symbols))
    ]
    dropped_symbols = [
        {
            "symbol": symbol,
            "name": (previous_symbols[symbol].metadata_snapshot or {}).get("name"),
            "strategies_hit": list(previous_symbols[symbol].hits or []),
        }
        for symbol in sorted(set(previous_symbols) - set(current_symbols))
    ]
    changes: dict[str, Any] = {
        "previous_date": str(previous.trade_date) if previous else None,
        "previous_regime": previous.market_regime if previous else None,
        "regime_changed": None
        if previous is None
        else previous.market_regime != summary.market_regime,
        "resonance_delta": None
        if previous is None
        else summary.resonance_count - previous.resonance_count,
        "hit_delta": None if previous is None else summary.hit_count - previous.hit_count,
        "new_symbol_count": len(new_symbols),
        "dropped_symbol_count": len(dropped_symbols),
        "new_symbols": new_symbols[:20],
        "dropped_symbols": dropped_symbols[:20],
    }
    return {
        "market": market,
        "trade_date": str(target),
        "source": summary.source,
        "adjustment": summary.adjustment,
        "status": summary.status,
        "run_id": summary.run_id,
        "market_regime": summary.market_regime,
        "benchmark": summary.benchmark,
        "counts": {
            "universe": summary.universe_count,
            "scanned": summary.scanned_count,
            "hits": summary.hit_count,
            "resonance": summary.resonance_count,
            "per_strategy": summary.strategy_hit_counts or {},
            "filtered": summary.filter_counts or {},
        },
        "top_resonance": picks,
        "sector_strength_ranking": _ranking(summary, rows),
        "changes_vs_previous_day": changes,
    }
