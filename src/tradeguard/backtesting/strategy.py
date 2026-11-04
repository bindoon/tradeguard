from decimal import Decimal

from tradeguard.backtesting.plugins import PortfolioStrategy
from tradeguard.screening.resonance import RULE_VERSION, family_evidence


class SignalPortfolio(PortfolioStrategy):
    name = "signal_portfolio"
    title = "信号组合与仓位管理"
    # Bump when family votes change. RULE_VERSION keeps the helper module in the snapshot.
    version = f"2-{RULE_VERSION}"

    def on_close(self, context) -> dict[str, Decimal]:
        config = context.config
        if config.combination is None:
            raise ValueError("缺少信号组合")
        candidates = []
        for symbol in context.universe:
            evidence = [
                (spec.name, context.signal(spec.name, symbol, spec.lookback))
                for spec in config.combination.signals
            ]
            votes = family_evidence(evidence)
            hits = sum(value is True for value in votes)
            unknown = sum(value is None for value in votes)
            threshold = (
                len(votes)
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
            high_breakout = any(
                name == "box_high_breakout" and value is True for name, value in evidence
            )
            candidates.append((symbol, hits, momentum, high_breakout))
        if config.rank_by == "momentum":
            # Missing momentum is not a neutral score and cannot rank as known.
            candidates = [item for item in candidates if item[2].is_finite()]

        def sort_key(item):
            symbol, hit_count, momentum, high_breakout = item
            prefer = 0 if high_breakout else 1
            if config.rank_by == "momentum":
                return (-momentum, prefer, symbol)
            if config.rank_by == "symbol":
                return (symbol,)
            return (-hit_count, prefer, symbol)

        candidates.sort(key=sort_key)
        weight = min(config.max_weight, config.invested_fraction / config.max_positions)
        if config.rebalance:
            selected = [item[0] for item in candidates[: config.max_positions]]
        else:
            selected = list(context.positions)
            for symbol, _, _, _ in candidates:
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
