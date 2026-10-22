# TradeGuard agent rules

Read README.md for commands; docs/architecture/README.md for system boundaries.

- Runtime is one Python package under src/tradeguard. CLI calls business services. FastAPI and web/ adapt the same services for the loopback-only console; cloud upload is not implemented.
- MySQL 8.4 is the runtime DB. Alembic owns schema changes; never use create_all as an upgrade.
- Failed account fetches must not publish a partial snapshot. Empty positions require a complete successful response.
- Manual import cannot claim broker_verified stop orders. A planned price is not an active broker order.
- Discipline checks use explicit, versioned personal rules and fresh snapshots. Unknown evidence returns needs_input.
- Preserve Decimal for money/risk comparisons and currency labels. Never add CNY/HKD/USD without explicit FX.
- Explicit scan date/source/adjustment are required. Never use a future bar or mix sources silently.
- Skills contain generic guidance. Never copy private journals, account IDs, credentials or personal seeds into Git.
- stdout is one JSON document for successful command parsing. Provider logs go to stderr. Do not print DB URLs/tokens.
- Test failures require checking behavior first; do not weaken assertions or skip tests to obtain a green run.
- The source strategies were ported from myskills; retain attribution in docs/provenance.md. Licensing remains to be selected before public release.

- TRADEGUARD_SELECTION_SOURCE_URL is a read-only import source, never a migration target. TRADEGUARD_DATABASE_URL is the independent runtime DB. Never print or commit their secrets.
- `pipeline daily --market CN` backfills A-share bars from akshare, falls back to baostock, and logs the source switch. Cached scans stay on an explicit `--source` such as `legacy_mysql` and do not hit the network. Do not fetch a whole market merely to obtain a passing data-quality status.

- CN/US/HK scans and charts must enforce market, source and date isolation. Never invent missing US data or neutral strength scores.
- Manual account patches preserve unmentioned fields and their observation times, the original statement and previous snapshot ID.
- Cache imports are genuine historical observations, not live broker verification. Never label a planned stop as active.
