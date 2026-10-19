---
name: stock-analyst
description: Research stocks, industries and primary financial sources; use TradeGuard for local market data and technical candidate screening. Covers A-share, Hong Kong and US research.
---

# Stock analyst

Use this skill to investigate industry trends, company fundamentals, valuation or the origin of a financial claim. Research is separate from permission to place a trade.

## Tools

Run from the installed TradeGuard checkout (`uv run tradeguard ...`) or use the installed `tradeguard` command. All successful commands emit a JSON envelope. Read status before data: partial is not full coverage.

1. `tradeguard doctor` checks the local installation and database.
2. `tradeguard market quality --date YYYY-MM-DD --source SOURCE` checks stored coverage. Its universe is stored securities, not proof of whole-market coverage.
3. `tradeguard market sync --date YYYY-MM-DD --symbol 600000.SH` fetches a bounded CN historical window using optional baostock dependencies. Without symbols it requests the provider's Shanghai/Shenzhen A-share universe.
4. `tradeguard scan run --date YYYY-MM-DD --source SOURCE` generates technical candidates, with data-readiness checks. It does not implement a full tradability filter or fundamental ranking.
5. `tradeguard scan results RUN_ID` reads a saved batch.
6. `tradeguard research save --file report.json` saves a report with primary-source evidence.

Use explicit market date, source and adjustment. Do not treat synthetic/example data as live prices. Sources may be delayed; retain observation period, disclosure date and retrieval time. Never silently replace a source or spend a paid data allowance.

## Research workflow

Read [primary data sources](references/data-sources.md) for industry hypotheses, numeric claims and financial evidence. Prefer regulators, exchanges, company IR and original statistical releases; data tools are acquisition channels, not necessarily the primary publisher.

Analyze the supply chain and test growth, profitability, barriers and bargaining power. Evaluate macro conditions, competitive position, supply-chain position, and financial quality/valuation. Separate facts, forecasts and inference; describe counterevidence and missing data. Use the user's requested market; do not invent a ticker or infer a currency from a company name.

An industry report should state the hypothesis, supporting/contradicting metrics, update cadence and risks. A company report should include valuation assumptions and risks, with links next to claims. Source-only questions do not need a stock rating. A technical scan match is a research candidate, not a recommendation or an order.

When the user intends to act, use trading-discipline with explicit personal rules and a fresh account snapshot. Do not infer approval from the research conclusion.
