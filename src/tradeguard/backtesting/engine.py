"""Daily close decisions and next-open execution with one shared Decimal ledger."""

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType
from typing import Any

import pandas as pd

from tradeguard.backtesting.plugins import canonical, fingerprint, signal_at

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass
class Position:
    quantity: int = 0
    cost: Decimal = ZERO
    price: Decimal = ZERO
    peak: Decimal = ZERO
    entered: int = 0
    lots: list[tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class PositionView:
    quantity: int
    average_cost: Decimal
    price: Decimal
    value: Decimal


class Context:
    """A strategy gets a fresh, time-bounded view, never the input data store."""

    def __init__(self, config, slices, signals):
        self.config = config.model_copy(deep=True)
        self.universe = tuple(config.symbols)
        self._slices = slices
        self._signals = signals
        self._cache: dict[tuple, Any] = {}
        self._calendar: list[str] = []
        self.current_date = ""
        self.positions: Any = MappingProxyType({})
        self.cash = ZERO
        self.total_value = ZERO
        self.unknown: set[tuple[str, str]] = set()
        self.decisions: dict[str, dict] = {}

    def history(self, symbol: str, count: int = 400, *, as_decimal: bool = False) -> pd.DataFrame:
        if symbol not in self.universe and symbol != self.config.benchmark:
            raise ValueError("策略请求了股票池外数据")
        if count < 1 or count > 400:
            raise ValueError("history count 必须在 1 至 400 之间")
        bars = [
            bar
            for bar in self._slices.get(symbol, {}).get("bars", [])
            if bar["date"] <= self.current_date
        ][-count:]
        return pd.DataFrame(
            [
                {
                    "date": bar["date"],
                    **{
                        key: Decimal(bar[key]) if as_decimal else float(bar[key])
                        for key in ("open", "high", "low", "close", "volume")
                    },
                }
                for bar in bars
            ]
        )

    def note_unknown(self, symbol: str) -> None:
        self.unknown.add((self.current_date, symbol))

    def explain(self, symbol: str, evidence: dict) -> None:
        if symbol not in self.universe:
            raise ValueError("决策解释超出股票池")
        self.decisions[symbol] = evidence

    def signal(self, name: str, symbol: str, lookback: int = 1):
        if name not in self._signals or symbol not in self.universe:
            raise ValueError("策略请求了未声明的信号或股票")
        values = []
        for day in self._calendar[-lookback:]:
            key = (name, symbol, day)
            if key not in self._cache:
                current = self.current_date
                self.current_date = day
                try:
                    frame = self.history(symbol)
                    result = (
                        signal_at(self._signals[name], frame, symbol, symbol, self._signals)
                        if not frame.empty and str(frame.iloc[-1]["date"]) == day
                        else None
                    )
                    self._cache[key] = result
                finally:
                    self.current_date = current
            result = self._cache[key]
            values.append(result["hit"] if result else None)
        if any(value is True for value in values):
            return True
        if len(values) < lookback or any(value is None for value in values):
            return None
        return False


def fee(notional: Decimal, side: str, execution) -> Decimal:
    return max(notional * execution.commission, execution.minimum_commission) + (
        notional * execution.sell_tax if side == "sell" else ZERO
    )


def round_lot(value: Decimal, lot: int) -> int:
    return max(0, int((value / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot)


def run(config, slices: dict, manifest: dict, signals: dict, strategy, progress=None) -> dict:
    calendar = manifest["calendar"]
    indexed = {
        symbol: {bar["date"]: bar for bar in data["bars"]} for symbol, data in slices.items()
    }
    context = Context(config, slices, signals)
    context._calendar = sorted(
        {
            bar["date"]
            for symbol in config.symbols
            for bar in slices[symbol]["bars"]
            if bar["date"] < calendar[0]
        }
    )
    cash = config.initial_cash
    positions: dict[str, Position] = {}
    orders: list[dict] = []
    trades: list[dict] = []
    curve = []
    peak_equity = config.initial_cash
    previous_quotes: dict[str, dict] = {}
    last_scheduled = None
    stale_marks: list[dict] = []
    for symbol, values in indexed.items():
        previous_bars = [value for day, value in values.items() if day < calendar[0]]
        if previous_bars:
            previous_quotes[symbol] = previous_bars[-1]

    for index, day in enumerate(calendar):
        quotes = {symbol: values[day] for symbol, values in indexed.items() if day in values}
        # Opening valuation uses only this open and marks already observed previously.
        opening_equity = cash + sum(
            (
                Decimal(quotes[symbol]["open"]) * pos.quantity
                if symbol in quotes
                else pos.price * pos.quantity
                for symbol, pos in positions.items()
            ),
            ZERO,
        )
        pending = [order for order in orders if order["status"] == "queued"]
        plans = []
        for order in pending:
            symbol = order["symbol"]
            bar = quotes.get(symbol)
            order["execution_date"] = day
            if bar is None:
                order.update(status="rejected", execution_reason="missing_bar")
                continue
            price = Decimal(bar["open"])
            if price <= 0 or Decimal(bar["volume"]) <= 0:
                order.update(status="rejected", execution_reason="suspended_or_invalid_price")
                continue
            held = positions[symbol].quantity if symbol in positions else 0
            target = round_lot(
                Decimal(order["target_weight"]) * opening_equity / price, config.execution.lot_size
            )
            # A zero target must liquidate odd lots too.
            delta = target - held
            if delta == 0:
                order.update(status="cancelled", execution_reason="already_at_target")
                continue
            plans.append((delta > 0, symbol, order, delta, price))
        # Sell first. Alphabetical tie-break makes shared cash allocation reproducible.
        for _, symbol, order, delta, opening_price in sorted(plans, key=lambda item: item[:2]):
            side = "buy" if delta > 0 else "sell"
            previous = previous_quotes.get(symbol)
            if previous is None or Decimal(previous["volume"]) <= 0:
                order.update(status="rejected", execution_reason="missing_prior_liquidity")
                continue
            move = opening_price / Decimal(previous["close"]) - ONE
            limit = config.execution.limit_pct
            if limit and ((side == "buy" and move >= limit) or (side == "sell" and move <= -limit)):
                order.update(status="rejected", execution_reason="configured_limit_move")
                continue
            price = opening_price * (
                ONE + config.execution.slippage_bps / 10000 * (ONE if side == "buy" else -ONE)
            )
            requested = abs(delta)
            capacity = round_lot(
                Decimal(previous["volume"]) * config.execution.prior_volume_fraction,
                config.execution.lot_size,
            )
            quantity = min(requested, capacity)
            reason = "prior_volume_cap" if quantity < requested else "filled"
            if side == "buy":
                if symbol not in positions and len(positions) >= config.max_positions:
                    order.update(status="rejected", execution_reason="max_positions")
                    continue
                affordable = round_lot(
                    cash / (price * (ONE + config.execution.commission)), config.execution.lot_size
                )
                if affordable < quantity:
                    quantity, reason = affordable, "insufficient_cash"
                # Minimum commission also has to fit; never overdraw to fill one lot.
                while (
                    quantity > 0
                    and price * quantity + fee(price * quantity, side, config.execution) > cash
                ):
                    quantity -= config.execution.lot_size
                    reason = "insufficient_cash"
            else:
                pos = positions[symbol]
                closeable = sum(
                    q
                    for bought, q in pos.lots
                    if index - bought >= config.execution.settlement_days
                )
                if closeable < quantity:
                    quantity, reason = closeable, "settlement_wait"
                quantity = min(quantity, pos.quantity)
            if quantity <= 0:
                order.update(status="rejected", execution_reason=reason)
                continue
            notional = price * quantity
            charges = fee(notional, side, config.execution)
            if side == "sell" and cash + notional < charges:
                order.update(status="rejected", execution_reason="insufficient_fee_cash")
                continue
            realized = None
            if side == "buy":
                cash -= notional + charges
                pos = positions.setdefault(symbol, Position(entered=index))
                pos.cost = (pos.cost * pos.quantity + notional + charges) / (
                    pos.quantity + quantity
                )
                pos.quantity += quantity
                pos.price = price
                pos.peak = max(pos.peak, price)
                pos.lots.append((index, quantity))
            else:
                pos = positions[symbol]
                realized = notional - charges - pos.cost * quantity
                cash += notional - charges
                remaining = quantity
                lots = []
                for bought, amount in pos.lots:
                    take = (
                        min(remaining, amount)
                        if index - bought >= config.execution.settlement_days
                        else 0
                    )
                    remaining -= take
                    if amount > take:
                        lots.append((bought, amount - take))
                pos.lots = lots
                pos.quantity -= quantity
                if pos.quantity == 0:
                    del positions[symbol]
            order.update(
                status="filled" if quantity == requested else "partial",
                execution_reason=reason,
                requested_quantity=requested,
                filled_quantity=quantity,
            )
            trades.append(
                {
                    "order_id": order["id"],
                    "symbol": symbol,
                    "side": side,
                    "signal_date": order["signal_date"],
                    "date": day,
                    "quantity": quantity,
                    "price": str(price),
                    "notional": str(notional),
                    "fee": str(charges),
                    "realized_pnl": str(realized) if realized is not None else None,
                    "reason": order["reason"],
                }
            )
            if cash < 0:
                raise ValueError("资金账本错误：现金为负")
        stale = []
        for symbol, pos in positions.items():
            if symbol in quotes:
                pos.price = Decimal(quotes[symbol]["close"])
                pos.peak = max(pos.peak, pos.price)
            else:
                stale.append(symbol)
                stale_marks.append({"date": day, "symbol": symbol})
        holdings = [
            {
                "symbol": symbol,
                "quantity": pos.quantity,
                "average_cost": str(pos.cost),
                "price": str(pos.price),
                "value": str(pos.price * pos.quantity),
                "unrealized_pnl": str((pos.price - pos.cost) * pos.quantity),
                "stale": symbol in stale,
            }
            for symbol, pos in sorted(positions.items())
        ]
        market_value = sum((pos.price * pos.quantity for pos in positions.values()), ZERO)
        equity = cash + market_value
        peak_equity = max(peak_equity, equity)
        curve.append(
            {
                "date": day,
                "cash": str(cash),
                "market_value": str(market_value),
                "equity": str(equity),
                "drawdown": str(equity / peak_equity - ONE),
                "exposure": str(market_value / equity) if equity else "0",
                "holdings": holdings,
            }
        )
        context.current_date = day
        context._calendar.append(day)
        context.positions = MappingProxyType(
            {
                symbol: PositionView(pos.quantity, pos.cost, pos.price, pos.quantity * pos.price)
                for symbol, pos in positions.items()
            }
        )
        context.cash, context.total_value = cash, equity
        if index == 0:
            strategy.initialize(context)
        stamp = date.fromisoformat(day)
        schedule_key = (
            day
            if config.schedule == "daily"
            else stamp.isocalendar()[:2]
            if config.schedule == "weekly"
            else (stamp.year, stamp.month)
        )
        targets = {}
        context.decisions = {}
        if schedule_key != last_scheduled:
            targets = strategy.on_close(context)
            last_scheduled = schedule_key
        targets = validate_targets(targets, config)
        reasons = {symbol: "portfolio_target" for symbol in targets}
        for symbol, pos in positions.items():
            # Missing today's close cannot trigger a price-based exit.
            if symbol not in quotes:
                continue
            pnl = pos.price / pos.cost - ONE if pos.cost else ZERO
            exit_reason = None
            if config.exits.stop_loss and pnl <= -config.exits.stop_loss:
                exit_reason = "stop_loss_at_close"
            elif config.exits.take_profit and pnl >= config.exits.take_profit:
                exit_reason = "take_profit_at_close"
            elif (
                config.exits.trailing_stop
                and pos.price / pos.peak - ONE <= -config.exits.trailing_stop
            ):
                exit_reason = "trailing_stop_at_close"
            elif (
                config.exits.max_holding_days
                and index - pos.entered + 1 >= config.exits.max_holding_days
            ):
                exit_reason = "max_holding_days"
            elif config.exits.signal_exit:
                frame = context.history(symbol)
                for name in (
                    [spec.name for spec in config.combination.signals] if config.combination else []
                ):
                    signal = signals[name]
                    if len(frame) >= signal.min_history and bool(
                        signal.exit_signal(frame.copy()).iloc[-1]
                    ):
                        exit_reason = "signal_exit:" + name
                        break
            if exit_reason:
                targets[symbol], reasons[symbol] = ZERO, exit_reason
                context.explain(
                    symbol,
                    {"summary": exit_reason, "strategy_decision": context.decisions.get(symbol)},
                )
        for symbol, weight in sorted(targets.items()):
            orders.append(
                {
                    "id": len(orders) + 1,
                    "symbol": symbol,
                    "signal_date": day,
                    "target_weight": str(weight),
                    "reason": reasons[symbol],
                    "status": "queued",
                    "execution_date": None,
                    "execution_reason": None,
                    "signal_evidence": {
                        spec.name: {
                            "hit": context.signal(spec.name, symbol, spec.lookback),
                            "lookback": spec.lookback,
                        }
                        for spec in (config.combination.signals if config.combination else [])
                    },
                    "decision_evidence": context.decisions.get(symbol),
                }
            )
        previous_quotes.update(quotes)
        if progress and (index % 20 == 0 or index == len(calendar) - 1):
            progress(index + 1, len(calendar))
    for order in orders:
        if order["status"] == "queued":
            order.update(status="expired", execution_reason="end_of_test")
    benchmark = config.benchmark
    benchmark_values = indexed.get(benchmark, {}) if benchmark else {}
    benchmark_ready = all(day in benchmark_values for day in calendar)
    baseline = Decimal(benchmark_values[calendar[0]]["close"]) if benchmark_ready else None
    for point in curve:
        point["benchmark_equity"] = (
            str(config.initial_cash * Decimal(benchmark_values[point["date"]]["close"]) / baseline)
            if baseline
            else None
        )
    warnings = list(manifest["warnings"])
    if not baseline:
        warnings.append("未选择基准或同源同复权基准覆盖不足；基准收益与超额收益为未知。")
    if context.unknown:
        warnings.append(
            f"共有 {len(context.unknown)} 个股票/日期的组合证据不足，未以未知信号建立仓位。"
        )
    metrics = calculate_metrics(config.initial_cash, curve, trades)
    if len(curve) < 21:
        warnings.append("收益观察不足 20 个，不展示年化收益与夏普；短样本不足以评估策略稳健性。")
    metrics["benchmark_return"] = (
        str(Decimal(curve[-1]["benchmark_equity"]) / config.initial_cash - ONE)
        if baseline
        else None
    )
    metrics["excess_return"] = (
        str(Decimal(metrics["total_return"]) - Decimal(metrics["benchmark_return"]))
        if baseline
        else None
    )
    report = {
        "schema_version": 1,
        "currency": config.currency,
        "price_model": config.price_model,
        "metrics": metrics,
        "curve": curve,
        "orders": orders,
        "trades": trades,
        "positions": curve[-1]["holdings"],
        "warnings": warnings,
        "unknown_signal_count": len(context.unknown),
        "stale_valuations": stale_marks,
        "assumptions": {
            "decision": "closed_daily_bar",
            "execution": "next_observed_open",
            "exits": "close_trigger_next_open",
            "liquidity": "previous_observed_bar_volume",
            "allocation": "sell_first_then_symbol_order",
            "annual_sessions": 252,
            "annual_metrics_min_returns": 20,
            "order_duration": "one_execution_attempt",
            "end_positions": "mark_to_close",
        },
    }
    report["result_hash"] = fingerprint(report)
    # Round-trip checks that every public artifact is strict JSON without NaN or Infinity.
    import json

    return json.loads(canonical(report))


def validate_targets(targets, config) -> dict[str, Decimal]:
    if not isinstance(targets, dict):
        raise ValueError("交易策略必须返回 {symbol: target_weight}")
    result = {}
    for symbol, value in targets.items():
        weight = Decimal(str(value))
        if (
            symbol not in config.symbols
            or not weight.is_finite()
            or weight < 0
            or weight > config.max_weight
        ):
            raise ValueError("目标仓位超出股票池或仓位限制")
        result[symbol] = weight
    if sum(result.values(), ZERO) > config.invested_fraction:
        raise ValueError("目标仓位合计超过配置的资金比例")
    if sum(value > 0 for value in result.values()) > config.max_positions:
        raise ValueError("目标持仓数超过配置上限")
    return result


def calculate_metrics(initial: Decimal, curve: list, trades: list) -> dict:
    last = Decimal(curve[-1]["equity"])
    notional = sum((Decimal(trade["notional"]) for trade in trades), ZERO)
    mean_equity = sum((Decimal(point["equity"]) for point in curve), ZERO) / len(curve)
    returns = [
        float(Decimal(curve[i]["equity"]) / Decimal(curve[i - 1]["equity"]) - ONE)
        for i in range(1, len(curve))
        if Decimal(curve[i - 1]["equity"]) > 0
    ]
    series = pd.Series(returns, dtype=float)
    volatility = float(series.std(ddof=1)) if len(returns) >= 2 else 0.0
    sells = [
        Decimal(trade["realized_pnl"]) for trade in trades if trade["realized_pnl"] is not None
    ]
    annualized = None
    if len(returns) >= 20 and last > 0:
        try:
            value = float(last / initial) ** (252 / len(returns)) - 1
            annualized = value if math.isfinite(value) else None
        except OverflowError:
            pass
    return {
        "initial_cash": str(initial),
        "final_equity": str(last),
        "total_return": str(last / initial - ONE),
        "annualized_return": annualized,
        "max_drawdown": str(min(Decimal(point["drawdown"]) for point in curve)),
        "sharpe_zero_rf": float(series.mean()) / volatility * 252**0.5
        if volatility and len(returns) >= 20
        else None,
        "turnover": str(notional / mean_equity) if mean_equity else None,
        "fees": str(sum((Decimal(trade["fee"]) for trade in trades), ZERO)),
        "trade_count": len(trades),
        "sell_fill_win_rate": str(Decimal(sum(pnl > 0 for pnl in sells)) / len(sells))
        if sells
        else None,
        "max_exposure": str(max(Decimal(point["exposure"]) for point in curve)),
        "observed_days": len(curve),
    }
