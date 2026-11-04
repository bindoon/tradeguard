"""Freeze cached observations, never fetch providers while replaying."""

from sqlalchemy import select

from tradeguard.backtesting.plugins import fingerprint
from tradeguard.db import session
from tradeguard.db.models import DailyBar, Security
from tradeguard.market.schemas import BarInput

FIELDS = ("open", "high", "low", "close", "volume", "amount")


def freeze(config, signals, required_history: int = 1) -> tuple[dict, dict]:
    symbols = sorted(set(config.symbols + ([config.benchmark] if config.benchmark else [])))
    slices = {}
    with session() as db:
        # InnoDB repeatable-read keeps these input queries on one consistent snapshot.
        securities = {
            security.symbol: security
            for security in db.scalars(select(Security).where(Security.symbol.in_(symbols)))
        }
        for symbol in symbols:
            security = securities.get(symbol)
            if security is None:
                if symbol == config.benchmark and symbol not in config.symbols:
                    continue
                raise ValueError(f"股票未登记：{symbol}")
            if security.market != config.market or security.currency != config.currency:
                raise ValueError("证券的市场/币种与实验不符")
            if security.security_kind == "index" and symbol in config.symbols:
                raise ValueError("指数不可作为股票持仓；可以用作基准")
            scope = (
                DailyBar.symbol == symbol,
                DailyBar.source == config.source,
                DailyBar.adjustment == config.adjustment,
            )
            before = db.scalars(
                select(DailyBar)
                .where(*scope, DailyBar.trade_date < config.start)
                .order_by(DailyBar.trade_date.desc())
                .limit(460)
            ).all()[::-1]
            period = db.scalars(
                select(DailyBar)
                .where(
                    *scope, DailyBar.trade_date >= config.start, DailyBar.trade_date <= config.end
                )
                .order_by(DailyBar.trade_date)
            ).all()
            for bar in [*before, *period]:
                BarInput.model_validate(
                    {
                        "symbol": symbol,
                        "trade_date": bar.trade_date,
                        "source": config.source,
                        "adjustment": config.adjustment,
                        **{field: getattr(bar, field) for field in FIELDS},
                    }
                )
            slices[symbol] = {
                "symbol": symbol,
                "name": security.name,
                "market": security.market,
                "currency": security.currency,
                "bars": [
                    {
                        "date": str(bar.trade_date),
                        **{
                            field: str(getattr(bar, field))
                            if getattr(bar, field) is not None
                            else None
                            for field in FIELDS
                        },
                    }
                    for bar in [*before, *period]
                ],
            }
    calendar = sorted(
        {
            bar["date"]
            for symbol in config.symbols
            for bar in slices[symbol]["bars"]
            if str(config.start) <= bar["date"] <= str(config.end)
        }
    )
    if len(calendar) < 2:
        raise ValueError("所选股票池在区间内至少需要两个已观察交易日")
    gaps = []
    for symbol in config.symbols:
        dates = {bar["date"] for bar in slices[symbol]["bars"]}
        missing = [day for day in calendar if day not in dates]
        if missing:
            gaps.append({"symbol": symbol, "missing": missing})
    if gaps and config.missing_data == "error":
        raise ValueError(
            f"股票池存在行情缺口：{gaps[0]['symbol']}，共 {len(gaps[0]['missing'])} 日"
        )
    required = max([signal.min_history for signal in signals.values()] + [required_history])
    warmup = [
        {
            "symbol": symbol,
            "observed": sum(bar["date"] <= calendar[0] for bar in slices[symbol]["bars"]),
            "required": required,
        }
        for symbol in config.symbols
    ]
    warnings = [
        "固定股票池研究，未重建历史全市场及退市股票，可能存在幸存者偏差。",
        "交易日来自所选股票缓存的日期并集，非独立核验的完整交易所日历。",
        "不使用当前行业、ST 或市值重建历史属性；未实现这些历史过滤。",
        "仅支持日线：收盘触发退出，下一已观察交易日开盘尝试成交，不模拟盘中止损路径。",
        "手数、结算等待、费用、涨跌幅与成交量限制为显式实验模型，非完整交易所规则。",
        "资金不含利息；成交无延迟/排队模型；期末持仓按末日收盘估值，不强制平仓。",
    ]
    if config.price_model == "adjusted_research":
        warnings.append(
            "使用冻结复权价格计算研究收益和模拟份额，不代表历史原始成交；未验证复权因子的历史可获得性。"
        )
    else:
        warnings.append("原始价模型未处理分红、拆股及配股等公司行为，不代表含分红的完整总回报。")
    if not config.execution.limit_pct:
        warnings.append("未配置涨跌幅限制；不能据此判断涨跌停订单可成交。")
    if any(item["observed"] < item["required"] for item in warmup):
        warnings.append("部分股票预热不足；相关日期的信号为未知，不冒充未命中。")
    if calendar[0] != str(config.start) or calendar[-1] != str(config.end):
        warnings.append(
            f"请求区间与观察日期不同：实际观察 {calendar[0]} 至 {calendar[-1]}，缺日不补造。"
        )
    if gaps:
        warnings.append("允许缺日跳过：缺行情无法成交；已有持仓保留上次估值并标记，不代表可交易。")
    manifest = {
        "frequency": "1d",
        "source": config.source,
        "adjustment": config.adjustment,
        "market": config.market,
        "currency": config.currency,
        "calendar": calendar,
        "series": [
            {"symbol": symbol, "rows": len(value["bars"]), "hash": fingerprint(value)}
            for symbol, value in sorted(slices.items())
        ],
        "gaps": gaps,
        "warmup": warmup,
        "warnings": warnings,
    }
    manifest["input_hash"] = fingerprint(slices)
    return slices, manifest
