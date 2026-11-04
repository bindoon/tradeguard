from decimal import Decimal

from tradeguard.backtesting.plugins import PortfolioStrategy


class SignalPortfolio(PortfolioStrategy):
    name = "signal_portfolio"
    title = "信号组合与仓位管理"

    def on_close(self, context) -> dict[str, Decimal]:
        config = context.config
        if config.combination is None:
            raise ValueError("缺少信号组合")
        candidates = []
        for symbol in context.universe:
            evidence = [
                context.signal(spec.name, symbol, spec.lookback)
                for spec in config.combination.signals
            ]
            hits = sum(value is True for value in evidence)
            unknown = sum(value is None for value in evidence)
            threshold = (
                len(evidence)
                if config.combination.mode == "all"
                else 1
                if config.combination.mode == "any"
                else config.combination.minimum
            )
            # A positive result is allowed only when independently proven.
            if hits < threshold:
                if hits + unknown >= threshold:
                    context.note_unknown(symbol)
                continue
            history = context.history(symbol, 21)
            momentum = (
                Decimal(str(history.iloc[-1]["close"])) / Decimal(str(history.iloc[0]["close"])) - 1
                if len(history) >= 21
                else Decimal("-Infinity")
            )
            candidates.append((symbol, hits, momentum))
        if config.rank_by == "momentum":
            # Missing momentum is not a neutral score and cannot rank as known.
            candidates = [item for item in candidates if item[2].is_finite()]
        candidates.sort(
            key=lambda item: (
                -item[1]
                if config.rank_by == "hits"
                else -item[2]
                if config.rank_by == "momentum"
                else 0,
                item[0],
            )
        )
        weight = min(config.max_weight, config.invested_fraction / config.max_positions)
        if config.rebalance:
            selected = [item[0] for item in candidates[: config.max_positions]]
        else:
            selected = list(context.positions)
            for symbol, _, _ in candidates:
                if symbol not in selected and len(selected) < config.max_positions:
                    selected.append(symbol)
        result = {symbol: weight for symbol in selected}
        if config.rebalance:
            result.update(
                {symbol: Decimal(0) for symbol in context.positions if symbol not in selected}
            )
        # Holding without a rebalance does not continually top up an existing position.
        else:
            result = {
                symbol: value for symbol, value in result.items() if symbol not in context.positions
            }
        return result
