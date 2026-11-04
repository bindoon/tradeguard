"""Read-only forward comparison of the two box breakout signals.

Signals are evaluated with the same ``signal_at`` path as scans and backtests.
The command only selects cached ``daily_bar`` rows. It does not fetch prices
or write scans, orders, or reports.
"""

import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

import pandas as pd
from sqlalchemy import select

from tradeguard.backtesting.plugins import discover, signal_at
from tradeguard.db import session
from tradeguard.db.models import DailyBar, Security
from tradeguard.screening.strategies.box_breakout import (
    BOX_PERIOD,
    MAX_BOX_RANGE_PCT,
    MIN_BOX_DAYS,
    VOLUME_MULTIPLIER,
)

STRATEGIES = ("box_breakout", "box_high_breakout")
HORIZONS = (5, 10, 20)
FALSE_BREAKOUT_BARS = 3
EXCURSION_BARS = 20
WARMUP_CALENDAR_DAYS = 700
FORWARD_CALENDAR_DAYS = 120
SIX = Decimal("0.000001")


def _text(value: Decimal) -> str:
    return format(value.quantize(SIX, rounding=ROUND_HALF_UP), "f")


def _distribution(values: list[Decimal]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(values),
        "mean": _text(sum(values, Decimal(0)) / len(values)),
        "median": _text(median(values)),
    }


def summarize_signals(events: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[str(event["strategy"])].append(event)
    summaries = []
    for name in STRATEGIES:
        rows = grouped.get(name, [])
        forward = {}
        for horizon in HORIZONS:
            returns = []
            for event in rows:
                closes = event["future_closes"]
                if len(closes) < horizon:
                    continue
                entry = event["close"]
                returns.append(closes[horizon - 1] / entry - 1)
            forward[str(horizon)] = _distribution(returns)
        favorable: list[Decimal] = []
        adverse: list[Decimal] = []
        false_count = 0
        false_sample = 0
        for event in rows:
            entry = event["close"]
            highs = event["future_highs"]
            lows = event["future_lows"]
            closes = event["future_closes"]
            if len(highs) >= EXCURSION_BARS and len(lows) >= EXCURSION_BARS:
                favorable.append(max(highs[:EXCURSION_BARS]) / entry - 1)
                adverse.append(min(lows[:EXCURSION_BARS]) / entry - 1)
            if len(closes) >= FALSE_BREAKOUT_BARS:
                false_sample += 1
                if any(close < event["box_top"] for close in closes[:FALSE_BREAKOUT_BARS]):
                    false_count += 1
        summaries.append(
            {
                "strategy": name,
                "title": "箱体突破" if name == "box_breakout" else "箱体高点突破确认",
                "signals": len(rows),
                "symbols": len({event["symbol"] for event in rows}),
                "forward_return": forward,
                "max_favorable_excursion": {
                    **_distribution(favorable),
                    "bars": EXCURSION_BARS,
                },
                "max_adverse_excursion": {**_distribution(adverse), "bars": EXCURSION_BARS},
                "false_breakout": {
                    "count": false_sample,
                    "false_count": false_count,
                    "rate": None
                    if not false_sample
                    else _text(Decimal(false_count) / false_sample),
                    "bars": FALSE_BREAKOUT_BARS,
                },
            }
        )
    return summaries


def _strategies() -> dict:
    installed = discover()
    return {name: installed[name].create({}) for name in STRATEGIES}


def _parameters(strategies: dict) -> dict:
    high = strategies["box_high_breakout"].parameters.model_dump(mode="json")
    return {
        "box_breakout": {
            "box_edge": "close",
            "box_period": BOX_PERIOD,
            "max_box_range_pct": MAX_BOX_RANGE_PCT,
            "min_box_days": MIN_BOX_DAYS,
            "volume_multiplier": VOLUME_MULTIPLIER,
            "breakout": "close > box_top",
            "volume": "volume > multiplier × volume_ma20",
        },
        "box_high_breakout": {"box_edge": "high_low", **high},
    }


def compare_box(
    source: str,
    start: date,
    end: date,
    adjustment: str = "forward",
    market: str = "CN",
    symbols: list[str] | None = None,
) -> dict:
    if market not in {"CN", "US", "HK"}:
        raise ValueError("market must be CN, US or HK")
    if adjustment not in {"forward", "none", "backward"}:
        raise ValueError("Unknown adjustment")
    if not source:
        raise ValueError("source is required")
    if start > end:
        raise ValueError("--start must be on or before --end")
    strategies = _strategies()
    warmup = start - timedelta(days=WARMUP_CALENDAR_DAYS)
    horizon = end + timedelta(days=FORWARD_CALENDAR_DAYS)
    events: list[dict] = []
    compared = 0
    with session() as db:
        query = (
            select(Security.symbol, Security.name)
            .join(DailyBar, DailyBar.symbol == Security.symbol)
            .where(
                Security.market == market,
                Security.security_kind != "index",
                DailyBar.source == source,
                DailyBar.adjustment == adjustment,
                DailyBar.trade_date >= start,
                DailyBar.trade_date <= end,
            )
            .group_by(Security.symbol, Security.name)
            .order_by(Security.symbol)
        )
        if symbols:
            query = query.where(Security.symbol.in_(symbols))
            kinds = dict(
                db.execute(
                    select(Security.symbol, Security.security_kind).where(
                        Security.symbol.in_(symbols), Security.market == market
                    )
                ).all()
            )
            unknown = [symbol for symbol in symbols if symbol not in kinds]
            if unknown:
                raise ValueError("股票未登记或不属于该市场：" + ", ".join(unknown))
            indexes = [symbol for symbol in symbols if kinds[symbol] == "index"]
            if indexes:
                raise ValueError("指数不参与箱体突破比较：" + ", ".join(indexes))
        names = dict(db.execute(query).all())
        if symbols:
            missing = [symbol for symbol in symbols if symbol not in names]
            if missing:
                raise ValueError("该来源和复权在区间内没有日线：" + ", ".join(missing))
        chosen = list(names)
        for offset in range(0, len(chosen), 200):
            batch = chosen[offset : offset + 200]
            rows = db.execute(
                select(
                    DailyBar.symbol,
                    DailyBar.trade_date,
                    DailyBar.open,
                    DailyBar.high,
                    DailyBar.low,
                    DailyBar.close,
                    DailyBar.volume,
                )
                .where(
                    DailyBar.symbol.in_(batch),
                    DailyBar.source == source,
                    DailyBar.adjustment == adjustment,
                    DailyBar.trade_date >= warmup,
                    DailyBar.trade_date <= horizon,
                )
                .order_by(DailyBar.symbol, DailyBar.trade_date)
            ).all()
            grouped: dict[str, list] = defaultdict(list)
            for row in rows:
                grouped[row.symbol].append(row)
            for symbol in batch:
                events.extend(
                    _signals_for_symbol(
                        symbol,
                        names[symbol] or symbol,
                        grouped.get(symbol, []),
                        start,
                        end,
                        strategies,
                    )
                )
            compared += len(batch)
            print(f"已比较 {compared}/{len(chosen)} 个标的", file=sys.stderr, flush=True)
    return {
        "read_only": True,
        "market": market,
        "source": source,
        "adjustment": adjustment,
        "start": str(start),
        "end": str(end),
        "symbols_compared": compared,
        "parameters": _parameters(strategies),
        "strategies": summarize_signals(events),
        "notes": [
            "只读取 daily_bar，不写扫描、回测或订单。",
            "信号使用与扫描相同的 screen()。箱体突破仍按收盘画箱；箱体高点突破确认按最高价/最低价画箱，并用收盘确认。",
            "收益以信号日收盘为基准。5、10、20 是其后的交易日根数，不含信号日本身；不足该长度不计入该期限。",
            "最大有利偏移取其后 20 根最高价，最大不利偏移取其后 20 根最低价，都相对信号日收盘；不足 20 根不计入。",
            "假突破：其后 3 根收盘中有一根低于该信号自己的 box_top。不足 3 根不计入比率。",
            f"每个标的读取信号日前最多 {WARMUP_CALENDAR_DAYS} 个自然日、信号区间结束后最多 {FORWARD_CALENDAR_DAYS} 个自然日的已入库日线。更早或更晚的行情不补造。",
            "两只策略在本比较里分别计数，不合并共振。",
        ],
    }


def _signals_for_symbol(symbol, name, rows, start, end, strategies) -> list[dict]:
    if not rows:
        return []
    frame = pd.DataFrame(
        {
            "date": [str(row.trade_date) for row in rows],
            "open": [float(row.open) for row in rows],
            "high": [float(row.high) for row in rows],
            "low": [float(row.low) for row in rows],
            "close": [float(row.close) for row in rows],
            "volume": [float(row.volume) for row in rows],
        }
    )
    found_events = []
    for index, row in enumerate(rows):
        if row.trade_date < start or row.trade_date > end:
            continue
        history = frame.iloc[: index + 1].tail(400)
        future = rows[index + 1 : index + 1 + EXCURSION_BARS]
        for strategy_name in STRATEGIES:
            found = signal_at(strategies[strategy_name], history, symbol, name, strategies)
            if not found or not found["hit"]:
                continue
            box_top = found["metadata"].get("box_top")
            if box_top is None:
                continue
            found_events.append(
                {
                    "strategy": strategy_name,
                    "symbol": symbol,
                    "date": str(row.trade_date),
                    "close": Decimal(str(row.close)),
                    "box_top": Decimal(str(box_top)),
                    "future_closes": [Decimal(str(item.close)) for item in future],
                    "future_highs": [Decimal(str(item.high)) for item in future],
                    "future_lows": [Decimal(str(item.low)) for item in future],
                }
            )
    return found_events
