"""Long-only daily research portfolios. All sizing and risk math stays Decimal."""

from decimal import Decimal

from pydantic import Field, field_validator

from tradeguard.backtesting.plugins import PortfolioStrategy
from tradeguard.market.schemas import normalize_symbol
from tradeguard.screening.strategies.classics import Parameters

ZERO = Decimal(0)


class RotationParameters(Parameters):
    lookback: int = Field(
        default=126,
        ge=2,
        le=300,
        title="动量回看周期",
        description="收益比较跨度，以已观察交易日计。",
    )
    skip: int = Field(
        default=21,
        ge=0,
        le=60,
        title="跳过近期日数",
        description="从收益窗口末端剔除近期 N 日；21 表示研究时跳过最近约一个月。",
    )
    top_n: int = Field(
        default=3,
        ge=1,
        le=100,
        title="排名入选数",
        description="最多持有排名靠前的 N 个已知标的，不能超过实验最多持仓数。",
    )


class DualParameters(Parameters):
    lookback: int = Field(
        default=252,
        ge=2,
        le=350,
        title="动量回看周期",
        description="比较当前与 N 日前的收盘价；同时用于相对排名和绝对门槛。",
    )
    top_n: int = Field(
        default=1,
        ge=1,
        le=100,
        title="风险资产入选数",
        description="从超过绝对门槛的风险资产中选择前 N 个，不能超过最多持仓数。",
    )
    minimum_return: Decimal = Field(
        default=ZERO,
        ge=Decimal("-0.99"),
        le=10,
        title="绝对价格收益门槛",
        description="0 表示价格收益必须为正；这是价格门槛，不是国债收益或含分红超额收益。",
    )
    defensive_symbol: str | None = Field(
        default=None,
        title="防御资产代码",
        description="可留空（持现金）；填写时必须已在同币种股票池中，且有当日行情。不会自动判断该资产是否低风险。",
    )

    @field_validator("defensive_symbol")
    @classmethod
    def symbol(cls, value):
        return normalize_symbol(value) if value else None


class TurtleParameters(Parameters):
    entry: int = Field(
        default=20,
        ge=2,
        le=300,
        title="突破通道周期",
        description="收盘必须超过此前 N 日最高价，窗口排除当日。",
    )
    exit: int = Field(
        default=10,
        ge=2,
        le=300,
        title="退出通道周期",
        description="收盘跌破此前 N 日最低价，产生全仓退出目标。",
    )
    atr_period: int = Field(
        default=20,
        ge=2,
        le=100,
        title="ATR 周期",
        description="真实波幅先以 N 日平均初始化，再按 Wilder 方式平滑；用于风险和加仓距离。",
    )
    risk_per_unit: Decimal = Field(
        default=Decimal("0.005"),
        gt=0,
        le=Decimal("0.1"),
        title="每单位计划风险比例",
        description="0.005 表示按权益的 0.5% 与 ATR 止损距离估算一个单位；跳空或成交限制可能使实际损失更大。研究参数不是个人纪律。",
    )
    stop_atr: Decimal = Field(
        default=Decimal(2),
        gt=0,
        le=10,
        title="止损 ATR 倍数",
        description="确认成交后，以新增批次含费用成本减去此倍数的计划 ATR，形成只上移的收盘止损参考。",
    )
    add_atr: Decimal = Field(
        default=Decimal("0.5"),
        gt=0,
        le=5,
        title="加仓 ATR 距离",
        description="收盘比上一次确认批次成本至少上涨此倍数 ATR，才可申请下一批。",
    )
    max_units: int = Field(
        default=4,
        ge=1,
        le=10,
        title="最多确认批次数",
        description="只在观察到持仓数量增加后计数；部分成交算一批，未成交不算。",
    )


class NativePortfolio(PortfolioStrategy):
    uses_signals = False
    min_history = 1

    def configure(self):
        pass

    def validate_config(self, config):
        if config.combination is not None:
            raise ValueError("此交易策略自行选股，请清空信号组合，避免把未采用的条件当作依据")
        if hasattr(self.parameters, "top_n") and self.parameters.top_n > config.max_positions:
            raise ValueError("策略入选数不能超过实验最多持仓数")


def momentum(context, symbol, lookback, skip=0):
    frame = context.history(symbol, lookback + skip + 1, as_decimal=True)
    if len(frame) < lookback + skip + 1 or str(frame.iloc[-1]["date"]) != context.current_date:
        context.note_unknown(symbol)
        return None
    return frame.iloc[-skip - 1]["close"] / frame.iloc[-lookback - skip - 1]["close"] - 1


def allocation(context, selected, unknown, top_n):
    """Keep unknown held positions; reserve their actual weight before new targets."""
    config = context.config
    protected = set(context.positions) & unknown
    slots = max(0, config.max_positions - len(protected))
    selected = selected[: min(top_n, slots)]
    reserved = (
        sum((context.positions[s].value for s in protected), ZERO) / context.total_value
        if context.total_value
        else ZERO
    )
    available = max(ZERO, config.invested_fraction - reserved)
    weight = (
        min(config.max_weight, config.invested_fraction / top_n, available / len(selected))
        if selected
        else ZERO
    )
    result = {
        symbol: ZERO
        for symbol in context.positions
        if symbol not in selected and symbol not in protected
    }
    result.update({symbol: weight for symbol in selected})
    return result


class RelativeMomentum(NativePortfolio):
    name = "relative_momentum"
    title = "多股票相对动量轮动"
    parameters_model = RotationParameters
    min_history = 148

    def configure(self):
        self.min_history = self.parameters.lookback + self.parameters.skip + 1

    def on_close(self, context):
        p = self.parameters
        scores, unknown = [], set()
        for symbol in context.universe:
            score = momentum(context, symbol, p.lookback, p.skip)
            if score is None:
                unknown.add(symbol)
            else:
                scores.append((symbol, score))
        scores.sort(key=lambda item: (-item[1], item[0]))
        selected = [symbol for symbol, _ in scores]
        targets = allocation(context, selected, unknown, p.top_n)
        for symbol, weight in targets.items():
            score = dict(scores).get(symbol)
            context.explain(
                symbol,
                {
                    "summary": "相对动量排名调仓" if weight else "未进入动量入选名单",
                    "momentum": str(score) if score is not None else None,
                    "rank": selected.index(symbol) + 1 if symbol in selected else None,
                },
            )
        return targets


class DualMomentum(NativePortfolio):
    name = "dual_momentum"
    title = "双动量（同币种价格版）"
    parameters_model = DualParameters
    min_history = 253

    def configure(self):
        self.min_history = self.parameters.lookback + 1

    def validate_config(self, config):
        super().validate_config(config)
        if (
            self.parameters.defensive_symbol
            and self.parameters.defensive_symbol not in config.symbols
        ):
            raise ValueError("防御资产必须显式加入同币种股票池")
        if len(config.symbols) <= bool(self.parameters.defensive_symbol):
            raise ValueError("双动量至少需要一个风险资产")

    def on_close(self, context):
        p = self.parameters
        candidates, unknown, scores = [], set(), {}
        for symbol in context.universe:
            if symbol == p.defensive_symbol:
                continue
            score = momentum(context, symbol, p.lookback)
            scores[symbol] = score
            if score is None:
                unknown.add(symbol)
            elif score > p.minimum_return:
                candidates.append((symbol, score))
        candidates.sort(key=lambda item: (-item[1], item[0]))
        selected = [symbol for symbol, _ in candidates]
        defensive = False
        if not selected and not unknown and p.defensive_symbol:
            frame = context.history(p.defensive_symbol, 1)
            if not frame.empty and str(frame.iloc[-1]["date"]) == context.current_date:
                selected, defensive = [p.defensive_symbol], True
            else:
                unknown.add(p.defensive_symbol)
                context.note_unknown(p.defensive_symbol)
        elif p.defensive_symbol:
            frame = context.history(p.defensive_symbol, 1)
            if frame.empty or str(frame.iloc[-1]["date"]) != context.current_date:
                unknown.add(p.defensive_symbol)
                context.note_unknown(p.defensive_symbol)
        if not selected and unknown and p.defensive_symbol in context.positions:
            unknown.add(p.defensive_symbol)
        targets = allocation(context, selected, unknown, 1 if defensive else p.top_n)
        for symbol, weight in targets.items():
            score = scores.get(symbol)
            context.explain(
                symbol,
                {
                    "summary": "无风险资产通过门槛，转向显式防御资产"
                    if defensive and weight
                    else "双动量入选"
                    if weight
                    else "未通过绝对门槛或不再入选",
                    "momentum": str(score) if score is not None else None,
                    "minimum_return": str(p.minimum_return),
                },
            )
        return targets


def atr_decimal(frame, period):
    ranges = [
        max(
            frame.iloc[i]["high"] - frame.iloc[i]["low"],
            abs(frame.iloc[i]["high"] - frame.iloc[i - 1]["close"]),
            abs(frame.iloc[i]["low"] - frame.iloc[i - 1]["close"]),
        )
        for i in range(1, len(frame))
    ]
    if len(ranges) < period:
        return None
    atr = sum(ranges[:period], ZERO) / period
    for value in ranges[period:]:
        atr = (atr * (period - 1) + value) / period
    return atr


class TurtleDaily(NativePortfolio):
    name = "turtle_daily"
    title = "海龟风格趋势组合（日线版）"
    parameters_model = TurtleParameters
    min_history = 21

    def configure(self):
        p = self.parameters
        self.min_history = max(p.entry, p.exit, p.atr_period) + 1
        self.states = {}
        self.pending = {}

    def validate_config(self, config):
        super().validate_config(config)
        if config.schedule != "daily":
            raise ValueError("日线海龟需要每日检查通道、止损和加仓，请选择 daily 调度")

    def on_close(self, context):
        p, config = self.parameters, context.config
        for symbol in list(self.states):
            if symbol not in context.positions:
                del self.states[symbol]
        # An order intention is not a fill. Confirm batches only from actual quantities.
        for symbol, plan in self.pending.items():
            pos = context.positions.get(symbol)
            if pos and pos.quantity > plan["quantity"]:
                added = pos.quantity - plan["quantity"]
                fill_cost = (
                    pos.average_cost * pos.quantity - plan["cost"] * plan["quantity"]
                ) / added
                old = self.states.get(symbol, {})
                self.states[symbol] = {
                    "units": old.get("units", 0) + 1,
                    "last_fill": fill_cost,
                    "atr": plan["atr"],
                    "stop": max(old.get("stop", ZERO), fill_cost - p.stop_atr * plan["atr"]),
                }
        self.pending = {}
        targets = {}
        exits, rows = set(), {}
        for symbol in context.universe:
            frame = context.history(symbol, 400, as_decimal=True)
            if len(frame) < self.min_history or str(frame.iloc[-1]["date"]) != context.current_date:
                context.note_unknown(symbol)
                continue
            atr = atr_decimal(frame, p.atr_period)
            if atr is None or atr <= 0:
                context.note_unknown(symbol)
                continue
            close = frame.iloc[-1]["close"]
            top = max(frame.iloc[-p.entry - 1 : -1]["high"])
            bottom = min(frame.iloc[-p.exit - 1 : -1]["low"])
            rows[symbol] = (close, top, atr)
            state = self.states.get(symbol)
            if symbol in context.positions and (
                close < bottom or (state and close <= state["stop"])
            ):
                targets[symbol] = ZERO
                exits.add(symbol)
                context.explain(
                    symbol,
                    {
                        "summary": "收盘跌破退出通道" if close < bottom else "收盘触发 ATR 止损",
                        "close": str(close),
                        "channel_low": str(bottom),
                        "stop": str(state["stop"]) if state else None,
                    },
                )
        held_value = sum(
            (pos.value for symbol, pos in context.positions.items() if symbol not in exits), ZERO
        )
        free = (
            max(ZERO, config.invested_fraction - held_value / context.total_value)
            if context.total_value
            else ZERO
        )
        slots = config.max_positions - len(context.positions) + len(exits)
        for symbol, (close, top, atr) in sorted(rows.items()):
            if symbol in exits or context.total_value <= 0:
                continue
            pos, state = context.positions.get(symbol), self.states.get(symbol)
            if pos:
                if (
                    not state
                    or state["units"] >= p.max_units
                    or close < state["last_fill"] + p.add_atr * state["atr"]
                ):
                    continue
            elif close <= top or slots <= 0:
                continue
            current = pos.value / context.total_value if pos else ZERO
            unit = p.risk_per_unit * close / (p.stop_atr * atr)
            increase = min(unit, free, max(ZERO, config.max_weight - current))
            if increase <= 0:
                continue
            targets[symbol] = current + increase
            free -= increase
            if not pos:
                slots -= 1
            self.pending[symbol] = {
                "quantity": pos.quantity if pos else 0,
                "cost": pos.average_cost if pos else ZERO,
                "atr": atr,
            }
            context.explain(
                symbol,
                {
                    "summary": "趋势满足距离条件，申请加仓"
                    if pos
                    else "收盘突破通道，申请首批仓位",
                    "close": str(close),
                    "channel_high": str(top),
                    "atr": str(atr),
                    "confirmed_units": state["units"] if state else 0,
                    "unit_weight_before_caps": str(unit),
                },
            )
        return targets


PORTFOLIOS = [RelativeMomentum, DualMomentum, TurtleDaily]
