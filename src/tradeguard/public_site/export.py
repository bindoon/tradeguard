import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from tradeguard.db import session
from tradeguard.db.models import DailyBar, ScanResult, ScanSummary, Security, now
from tradeguard.market.schemas import normalize_symbol
from tradeguard.workspace.schemas import Scope


def public_data(scope: Scope, target: date, symbols: list[str]) -> dict:
    """Construct a positive field allowlist; never dump ORM objects or private reports."""
    if target > now().astimezone(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("不能公开未来交易日")
    chosen = list(dict.fromkeys(normalize_symbol(s) for s in symbols))
    if not chosen or len(chosen) > 50:
        raise ValueError("Explicitly select 1–50 public symbols")
    with session() as db:
        summary = db.scalar(
            select(ScanSummary).where(
                ScanSummary.market == scope.market,
                ScanSummary.source == scope.source,
                ScanSummary.adjustment == scope.adjustment,
                ScanSummary.trade_date == target,
            )
        )
        stocks = []
        for symbol in chosen:
            security = db.get(Security, symbol)
            if security is None or security.market != scope.market:
                raise ValueError("Public symbol does not belong to the requested market")
            bars = db.scalars(
                select(DailyBar)
                .where(
                    DailyBar.symbol == symbol,
                    DailyBar.source == scope.source,
                    DailyBar.adjustment == scope.adjustment,
                    DailyBar.trade_date <= target,
                )
                .order_by(DailyBar.trade_date.desc())
                .limit(60)
            ).all()[::-1]
            hit = db.get(ScanResult, (summary.run_id, symbol)) if summary else None
            stocks.append(
                {
                    "symbol": symbol,
                    "name": security.name,
                    "currency": security.currency,
                    "industry": security.industry,
                    "bars": [
                        {
                            "date": str(b.trade_date),
                            "open": str(b.open),
                            "high": str(b.high),
                            "low": str(b.low),
                            "close": str(b.close),
                        }
                        for b in bars
                    ],
                    "strategies": list(hit.hits) if hit else [],
                    "resonance_count": len(hit.hits) if hit else None,
                }
            )
        return {
            "schema_version": 1,
            "generated_at": now().isoformat(),
            "trade_date": str(target),
            **scope.model_dump(),
            "summary": None
            if summary is None
            else {
                "status": summary.status,
                "market_regime": summary.market_regime,
                "universe_count": summary.universe_count,
                "scanned_count": summary.scanned_count,
                "hit_count": summary.hit_count,
                "resonance_count": summary.resonance_count,
            },
            "stocks": stocks,
        }


def export_site(scope: Scope, target: date, symbols: list[str], output: Path) -> dict:
    data = public_data(scope, target, symbols)
    output.mkdir(parents=True, exist_ok=True)
    # A fresh directory avoids accidentally shipping a previously copied private file.
    if any(output.iterdir()):
        raise ValueError("Public export directory must be empty; choose a new directory")
    payload = (
        json.dumps(data, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    template = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    (output / "index.html").write_text(
        template.replace("__PUBLIC_DATA__", payload), encoding="utf-8"
    )
    return {
        "status": "success",
        "output": str(output.resolve()),
        "symbols": len(symbols),
        "market": scope.market,
        "source": scope.source,
        "trade_date": str(target),
        "private_data": False,
    }
