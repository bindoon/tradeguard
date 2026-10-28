# Source provenance

- `src/tradeguard/screening/strategies/` and `screening/indicators.py` were ported from `myskills/tools/stock-scanner/` on 2026-10-18. Initial changes are package imports and formatting. Existing signal semantics were retained.
- Default scanner uses ma_golden_cross, macd_golden_cross, rsi_rebound, bollinger_breakout and box_breakout. The sixth pattern is retained in the registry and is not run by the default scanner because it requires prior-signal evidence.
- `skills/stock-analyst` and `skills/trading-discipline` were synced from the corresponding myskills directories on 2026-10-28. The Chinese manuals are kept as written, including Bouda's trading habits in `skills/trading-discipline/references/`. TradeGuard CLI wiring and `skills/stock-analyst/references/daily-top5.md` are local. Account identifiers, credentials and personal seeds are not part of these files.
- `/Users/bouda/work/selection` revision `6dfbe07` supplied workflow context. The web/ frontend was copied from litefront at revision 6dfbe070 and adapted to TradeGuard APIs. Tradability filtering and sector strength are implemented in Python; live backtest is not ported.
- The package is independently implemented around Python, SQLAlchemy and Alembic; ruyi supplied engineering context, not runtime code.
- [OpenStock](https://github.com/Open-Dev-Society/OpenStock), revision `855ca6af33ae0b86f8835ecda6c31707f4ec3891`, informed the 2026-10-23 watchlist, search, tabs and chart-preference interaction design. No OpenStock source code or assets were copied; its AGPL-3.0 code is not included.

No repository license has been selected. Keep the repository private until source rights and the intended license are settled. This document records provenance; it does not grant third-party rights.

- The 2026-10-27 scan workflow, history metrics and stock-profile layout were checked against the live stock.zhiyu.hk `/scan` and `/stock/sz.002355` interactions. The local selection checkout was revision `415b11d9efff7545caac86beafacd8a8c3cc93a0`; it predates those routes. TradeGuard retains its own five default strategies, saved execution data and real-account boundaries.

- Broker order normalization follows [Futu trading definitions](https://openapi.futunn.com/futu-api-doc/trade/trade.html) and [Longbridge order details](https://open.longbridge.com/docs/trade/order/order_detail). Standalone touched orders are not assumed to be verified stop-loss intent.

- Longbridge fund unit/NAV fields follow [fund positions](https://open.longbridge.com/zh-CN/docs/trade/asset/fund); unit NAV is multiplied by holding units, and its observation date is preserved.
