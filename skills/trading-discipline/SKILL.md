---
name: trading-discipline
description: Check proposed stock purchases and additions against explicit personal rules, current portfolio evidence and stop plans using TradeGuard. Also guide manual review of sales, options and emotionally driven trades.
---

# Trading discipline

Use for an intended transaction. Numerical decisions come from the tool; personal judgment and missing evidence must remain explicit.

## Before checking

- Ask for the account and proposed action. Never read someone else's personal history as this user's policy.
- `tradeguard portfolio report --account ACCOUNT_ID` shows the latest complete snapshot and timestamp.
- Manual accounts use `tradeguard portfolio import --file snapshot.json`. Imports cannot claim broker-verified orders. Import only information the user explicitly provided; keep private files out of Git.
- `tradeguard discipline rules-import --file rules.json` creates an immutable rule-profile version. Thresholds in examples are examples; the user must select their own rules.
- Build a JSON trade card with account_id, symbol, currency, action, style, quantity, price, stop_price, stop_evidence, fees and thesis. Validate source price/time outside the tool before constructing the card.
- `tradeguard discipline check --profile PROFILE_ID --file intent.json` persists a check linked to its rules and snapshot.

## Interpret the result

`blocked` identifies rule violations. `needs_input` means evidence is insufficient. Never paraphrase either as permission to buy. `pass` means the supplied purchase/addition passed those configured checks; execution, liquidity, slippage and broker stop activation still require review. Manually confirmed plans are labeled manual; a planned stop price is not an active broker order.

Current checks cover buy/add long-stock intents, post-trade account exposure, planned per-trade loss, available cash, zero leverage, monthly drawdown threshold, freshness, FX and protective-stop coverage for existing holdings. Trend additions below cost are blocked. Value additions require human fundamental review.

The initial tool does not automatically assess sell/reduce intents, derivatives, cross-account exposure, or the user's emotional condition. Explain this boundary and review these actions with the user; do not route them through a fake stock purchase to obtain a pass. An assessment is not an order. No tools in this project submit or cancel broker orders.

When several accounts hold the same security, aggregate exposure separately before acting; the initial numeric check covers the named account only. The user's own stronger restrictions take precedence over example settings.
