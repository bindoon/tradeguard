"""Explicit US/HK/CN daily-history synchronization through the configured Longbridge SDK."""

import os
import re
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from tradeguard.config import settings
from tradeguard.db import session
from tradeguard.db.models import Security
from tradeguard.market.schemas import BarInput, normalize_symbol
from tradeguard.market.service import save_bars


def candles_to_bars(symbol, candles, market, name=""):
    zone = ZoneInfo(
        "America/New_York"
        if market == "US"
        else "Asia/Hong_Kong"
        if market == "HK"
        else "Asia/Shanghai"
    )
    return [
        BarInput(
            symbol=symbol,
            name=name or symbol,
            source="longbridge",
            adjustment="forward",
            trade_date=c.timestamp.astimezone(zone).date(),
            open=Decimal(str(c.open)),
            high=Decimal(str(c.high)),
            low=Decimal(str(c.low)),
            close=Decimal(str(c.close)),
            volume=Decimal(str(c.volume)),
            amount=Decimal(str(c.turnover)) if getattr(c, "turnover", None) is not None else None,
        )
        for c in candles
    ]


def sync(target: date, start: date, symbols: list[str] | None, market: str):
    if market not in {"CN", "US", "HK"} or start > target:
        raise ValueError("Invalid market or date window")
    suffix = {"CN": (".SH", ".SZ", ".BJ"), "US": (".US",), "HK": (".HK",)}[market]
    with session() as db:
        known = {
            s.symbol: s.name
            for s in db.scalars(select(Security).where(Security.market == market)).all()
        }
    selected = [normalize_symbol(s) for s in symbols] if symbols else list(known)
    if not selected:
        raise ValueError("Add symbols explicitly or import a market universe first")
    if any(not s.endswith(suffix) for s in selected):
        raise ValueError("Symbols do not belong to the selected market")
    cfg = settings()
    key, secret, token = (
        cfg.longbridge_app_key,
        cfg.longbridge_app_secret,
        cfg.longbridge_access_token,
    )
    if not key or not secret or not token:
        raise ValueError("Configure Longbridge API credentials first")
    os.environ["LONGBRIDGE_REGION"] = cfg.longbridge_region
    try:
        from longbridge.openapi import AdjustType, Config, Period, QuoteContext

        context = QuoteContext(
            Config.from_apikey(
                key.get_secret_value(), secret.get_secret_value(), token.get_secret_value()
            )
        )
        failed = []
        saved = 0
        stale = []
        for symbol in selected:
            candles = context.history_candlesticks_by_date(
                symbol, Period.Day, AdjustType.ForwardAdjust, start, target
            )
            bars = candles_to_bars(symbol, candles, market, known.get(symbol, ""))
            if not bars:
                failed.append(symbol)
                continue
            saved += save_bars(bars)["rows"]
            if max(b.trade_date for b in bars) != target:
                stale.append(symbol)
        return {
            "market": market,
            "source": "longbridge",
            "date": str(target),
            "rows": saved,
            "requested": len(selected),
            "failed": failed,
            "stale": stale,
            "status": "partial" if failed or stale else "success",
        }
    except ImportError:
        raise ValueError("Install the SDK: uv sync --extra longbridge") from None
    except Exception as exc:
        code = re.search(r"\bcode=(\d+)", str(exc))
        if code and code.group(1) == "401003":
            raise RuntimeError("Longbridge token expired (401003)") from None
        if isinstance(exc, ValueError):
            raise
        raise RuntimeError(
            "Longbridge market synchronization failed (" + type(exc).__name__ + ")"
        ) from None
