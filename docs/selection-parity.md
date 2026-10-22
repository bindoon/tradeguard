# selection 日更流水线对照

参考实现是 `github.com/bindoon/selection` 的 `main` @ `6dfbe07`（stock.zhiyu.hk 的来源）。本环境的 GitHub 凭据读不到这个私有仓库，不能逐行核对那次提交。下面的差异以仓库里已经移植的策略模块、`docs/provenance.md` 记录的 litefront，以及这次要落地的日更契约为准。TradeGuard 运行时不调用 selection 的 API，也不连接它的 SQLite。

## 这次补上的缺口

- `pipeline daily` 以前必须给 `--date`，默认读 `legacy_mysql` 缓存，不会回补全市场。
- 没有 akshare 适配器，也没有「主源失败再换 baostock」的显式事件。
- 证券表没有 ST 标记、行业板块字段和指数/股票区分；ST 只看名称。
- 扫描摘要只在 `job_run.details` 里，没有按交易日可覆盖的 `scan_summary`。
- 命中行没有共振次数、行业强度列，也没有策略原因。
- 没有给 Agent 用的 `report daily`。
- 个股图没有策略信号点；单日结果不能按列排序或按策略过滤。
- 源库只在会话里 `SET SESSION TRANSACTION READ ONLY`，没有共享的语句级写保护。
- `job_run` 不会把超时的 running/queued 标成 stale。
- 没有 03:30 Asia/Shanghai 的 launchd / cron 模板。

## 与 selection 对齐、且已经在本仓库里的行为

- 初筛：剔除 ST、上市不足 365 天、停牌（成交量为 0）、近 5 日日均成交额低于 1 亿元。主板涨跌停阈值 ±9.5%。
- 五个策略：均线金叉（两天前 MA5 上穿 MA10，且 MA5>MA10>MA20>MA60）、MACD 金叉（当日上穿、零轴上方、收盘在 MA20 上）、RSI 反弹（上穿 30、阳线、量大于 20 日均量）、布林带首次放量突破、箱体突破（20 日振幅 < 15%，量 > 1.5×MA20）。
- 共振是同一标的当日命中的策略数。行业强度用行业涨幅、成交额能量和基准超额；没有基准时保持未知，不填中性分。
- 市场状态：上证指数收盘相对 MA20，以及 MA20 近 5 日方向，得到 bull / bear / neutral。
- 页面路径：`/scan`、`/scan/:date`、`/screener`、`/stock/:code`、`/portfolio`。`/monitor` 打开真实持仓，不再做模拟仓。

## 仍然不同的地方

- selection 用 SQLite 的 `scan_results` / `scan_summaries`。这里对应 MySQL 的 `scan_result`、`scan_summary` 和 `job_run`，由 Alembic 管理。
- 主板以外保留交易所带宽：创业板/科创板 19.5%，北交所 29.5%。若 selection 对所有板块都用 9.5%，则 10%–19% 的创业板涨幅会被它留下、被这里剔除。
- `two_bullish_one_bearish` 仍不在每日五个策略里，因为它依赖前序信号。
- 不移植模拟盘、回测和云端上传。
- akshare 的成交量单位是手，入库前乘以 100，与 baostock 的「股」对齐。
- 美股和港股仍要显式指定来源。这条日更命令只覆盖 A 股。
- 旧行情 `legacy_mysql` 截止 2026-06-25，来源字段保持不变。新的 akshare/baostock 序列单独存放，扫描不把两种价格接成一根 K 线。
