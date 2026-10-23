# TradeGuard

Agent 驱动的股票研究、行情同步、策略扫描、真实持仓与交易纪律工具。Python 负责数据和计算，React + TypeScript 负责本地控制台。CLI、HTTP 适配层调用同一业务服务，MySQL 是独立运行数据库。

## 启动

需要 Python 3.12、uv、Docker、Node.js 和 pnpm。

```bash
cp .env.example .env
uv sync --extra market --extra longbridge --extra futu
docker compose up -d --wait
uv run alembic upgrade head
pnpm --dir web install --frozen-lockfile
pnpm --dir web build
uv run tradeguard serve
```

打开 http://127.0.0.1:8188 。MySQL 8.4 只监听本机 53306，开发账号仅供本机使用。密钥写在被忽略的 `.env`，勿提交个人账户或券商凭证。前端开发可单独运行 `pnpm --dir web dev --host 127.0.0.1`，地址 5178，代理本机 8188。

## 迁移

结构只由 Alembic 升级，运行库地址只来自 `TRADEGUARD_DATABASE_URL`。

```bash
uv run alembic upgrade head
```

本地库是 `compose.yaml` 里的 MySQL，监听 `127.0.0.1:53306`，库名 `tradeguard`。之后改到阿里云 RDS 时只换这一条环境变量，不改代码、不把 RDS 写成源库：

```bash
# .env
TRADEGUARD_DATABASE_URL=mysql+pymysql://USER:PASSWORD@rm-xxxx.mysql.rds.aliyuncs.com:3306/tradeguard?charset=utf8mb4
uv run alembic upgrade head
```

`TRADEGUARD_SELECTION_SOURCE_URL` 和 `TRADEGUARD_PORTFOLIO_SOURCE_URL` 只读。连接会执行 `SET SESSION TRANSACTION READ ONLY`，语句守卫会拒绝 INSERT/UPDATE/DELETE。旧库 `mkt_bar_sync_runs`、`mkt_strategy_scan_runs` 里停在 `running` 的行会被忽略，不作为续跑锁。

## 回补、每日流水线与报告

`pipeline daily --market CN` 从运行库里最后一根 A 股日线之后补到最近一个已收盘交易日（上海时间 16:00 之前取前一自然日，再落到交易日）。akshare 为主、baostock 为备；切换会写入 `run_event.stage=source_fallback`，当次扫描不混用两个来源的价格。已有该来源最新 K 线的标的会跳过。证券池会更新名称、ST 标记、上市日期和行业。然后按 selection 的门槛做初筛，跑五个策略，计共振、行业强度和市场状态，并写入 `scan_summary`。

第一次给某个来源建序列时，会额外回看约 550 天，供均线和 MACD 使用。这是该来源自己的前复权序列，不会把 `legacy_mysql` 的价格改标成 akshare。

```bash
uv sync --extra market
uv run tradeguard pipeline daily --market CN
uv run tradeguard pipeline daily --market CN --date 2026-06-26
uv run tradeguard pipeline daily --market CN --from 2026-06-26 --to 2026-10-21
uv run tradeguard report daily --date 2026-10-21 --market CN
```

`--date` 与 `--from/--to` 不能同时使用。显式 `--source legacy_mysql`（或其它缓存来源）只扫已有行情，不联网。`--source baostock --refresh` 则只用 baostock 做全池回补。akshare 默认 4 个并发、每次请求至少间隔 0.2 秒，可用 `TRADEGUARD_AKSHARE_WORKERS` 和 `TRADEGUARD_AKSHARE_MIN_INTERVAL` 调整。超过 6 小时仍为 running 的 `job_run` 会被标成 stale。

报告是一条 JSON，包含市场状态、各策略命中数、共振最高的标的和原因、行业强度排序，以及相对前一扫描日的新增与消失。stdout 仍是外面再包一层的单条 JSON。

定时任务模板在 `deploy/`，每天 03:30（Asia/Shanghai）。不要在仓库里安装它，说明见 `deploy/README.md`。

## 行情与扫描

```bash
uv run tradeguard market import-legacy --max-rows 1000
uv run tradeguard market import-legacy --resume-run IMPORT_RUN_ID
uv run tradeguard market stats --market CN --source legacy_mysql
uv run tradeguard scan run --market CN --date 2026-06-25 --source legacy_mysql
uv run tradeguard pipeline daily --market CN --date 2026-06-25 --source legacy_mysql
```

`TRADEGUARD_SELECTION_SOURCE_URL` 是已有行情库的只读导入源；`TRADEGUARD_DATABASE_URL` 是独立的运行库。每批 upsert 和导入游标同事务提交，按批次断点续传，MySQL 连接级锁防止重复导入。来源/复权参与行情唯一键。

本机已导入 1,858,615 条有效旧日线，源表 1,859,559 条中 944 条不完整记录被跳过。另有一次独立 baostock 单股真实采集；所有来源分开存储。旧库行情截止 **2026-06-25**，不能作为今天行情使用。

```bash
uv run tradeguard market sync --market CN --source baostock --date 2026-10-16 --symbol 600000.SH
uv run tradeguard market sync --market US --source longbridge --date 2026-10-16 --symbol AAPL.US
uv run tradeguard market quality --market CN --date 2026-10-16 --source baostock
```

日期为示例，应选择已完成交易日。默认日常任务读取缓存；`--refresh` 才联网。baostock 支持沪深 A 股，Longbridge 支持已配置权限的市场；不静默换源。US/HK 从明确指定的证券或已登记证券池采集，当前不声称覆盖整个市场。

五个主策略为均线金叉、MACD 金叉、RSI 反弹、布林带突破、箱体突破。扫描包含 ST、停牌、上市时间、流动性和 A 股涨跌幅过滤；参数随市场变化。缺上市日期且历史无法证明年龄时明确提示，缺基准指数时相对强度和市场环境为未知。每个批次保留输入摘要、策略版本、进度事件、过滤原因和缺口；缺行情标为 partial。

控制台提供市场切换、历史扫描（`/scan`）、单日结果（`/scan/:date`，可按共振、行业强度、代码、名称排序，并按行业和策略过滤）、筛选器（`/screener`）、个股 K 线与策略信号（`/stock/:code`）以及真实持仓（`/portfolio`，`/monitor` 打开同一持仓页）。不会自动混用 A 股与美股数据。扫描详情图表使用该批次的来源与交易日。信号标记只画在同一来源的已保存扫描上。前端以 selection/litefront 为参考，模拟买卖已替换为真实账户展示；目前不提供回测和实盘下单。

```bash
uv run tradeguard serve
```

浏览器打开 http://127.0.0.1:8188 。

## 真实持仓与口述更新

```bash
uv run tradeguard portfolio import-existing
uv run tradeguard portfolio account-add --help
uv run tradeguard portfolio update --account ACCOUNT_ID --file private/update.json
uv run tradeguard portfolio report --account ACCOUNT_ID
uv run tradeguard portfolio sync --broker longbridge --account ACCOUNT_ID --base-currency HKD
uv run tradeguard portfolio sync --broker futu --account ACCOUNT_ID --base-currency HKD
```

`TRADEGUARD_PORTFOLIO_SOURCE_URL` 是已有持仓库的只读来源。本机已导入真实历史缓存；没有同步记录的账户显示未知，不生成模拟资产。历史用户填写的止盈/止损保留 planned 或 manually_confirmed 证据，不冒充已核验的券商订单。

无 API 的账户由 Agent 根据用户明确口述生成 `ManualPatch` JSON，包含 `statement` 原话、`as_of` 和需要修改的 `positions` / `orders`。未提及的持仓和订单保留；数量改动而没有新估值时清空估值。数量为零代表移除，`replace_orders` 只在明确重建全部订单时使用。保留原快照、前一快照引用、各项观察时间；修改一只股票不会刷新全部资产时间。

券商读取失败不覆盖上次成功快照。长桥和富途需用户配置有效凭证/OpenD 后才能进行新的实时同步；已导入的缓存仍可查看。长桥采集同时保留股票与基金份额/净值，已拆分的股票与基金子组合延续原范围；子组合不复制整个券商账户资产和现金，避免重复统计。长桥 standalone LIT/MIT 保留为方向未知的条件单，不能推断为止损；富途 STOP、触及止盈和跟踪止损按官方类型分别保存。金额与风险计算使用 Decimal，不直接合计不同币种。

## 买入前纪律与研究

```bash
uv run tradeguard discipline rules-import --file private/rules.json
uv run tradeguard discipline check --profile PROFILE_ID --file private/intent.json
uv run tradeguard research save --file private/report.json
```

`examples/` 只含合成验收数据，不能自动当作个人纪律。规则显式导入并版本化；检查买入/加仓后的单账户单股占比、计划损失、现金、杠杆、回撤、新鲜度和止损证据。不足返回 needs_input，违反规则返回 blocked。通过只代表已实现检查通过，不是交易建议或下单授权。研究报告保留正文、来源、观察周期、发布时间与检索时间。

将 `skills/stock-analyst` 和 `skills/trading-discipline` 安装或链接到 Agent 宿主技能目录。正常 CLI stdout 是单条 JSON，供应商日志走 stderr。退出码 0 完成、1 错误、2 部分完成、3 待补信息、4 纪律拦截。

## 开发与边界

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/tradeguard
uv run pytest -q
pnpm --dir web test
pnpm --dir web build
```

集成测试使用独立临时 MySQL 数据库，通过 `TRADEGUARD_TEST_ADMIN_URL` 配置测试管理员；不会清空应用库。数据库结构由 SQLAlchemy + Alembic 管理。架构见 [docs/architecture/README.md](docs/architecture/README.md)，来源与授权边界见 [docs/provenance.md](docs/provenance.md)。线上发布、鉴权、多用户及数据上传尚未实现，HTTP 控制台仅供本机运行。

## 个人工作台、自选与提醒

首页现在展示当前市场/来源/复权的最近扫描、候选、与前次扫描的变化、行业强度、个人自选、持仓复核与最近纪律检查。持仓复核使用最近保存的真实观察和该来源收盘价：触及已记录退出价格时展示依据；缺行情、快照过期或保护单证据不足时提示先补证据。它不是完整卖出决策引擎，不会自动下单，也不会把计划标成券商挂单。

- `/watchlist`：从扫描或个股页加入，保存观察原因和关联批次；自选独立于真实持仓。
- 全局搜索：`⌘K` / `Ctrl+K` 搜索本地证券。股票标签在本浏览器保留，带有各自市场、来源、复权和历史截止日。
- 个股页：记住日线范围、均线、布林带和信号开关；用个人明确选择的规则版本、账户和拟交易做买入/加仓纪律检查。没有规则时提示导入，不套用示例阈值。
- `/alerts`：创建价格条件后，可手动评估已保存日线，或运行下面的 CLI。价格条件仅使用创建当日及之后的观察；旧缓存不会触发新条件。新信号和过期快照也可形成去重提醒。提醒只在手动/命令评估时产生，不声称全天候盘中监控。

```bash
uv run tradeguard workspace report --market CN --source baostock
uv run tradeguard workspace refresh --market CN --source baostock
uv run tradeguard workspace watch --file private/watch.json
uv run tradeguard workspace alert --file private/alert.json
```

`workspace report` 是给 Agent 做个人研究与买卖讨论的私有证据包，包含候选、持仓复核、显式个人规则与近期检查。不得当作公共站数据源。`workspace refresh` 不联网，适合由你自己的本地调度在日线任务之后显式执行；不会安装任何定时任务。

自选 JSON 形如 `{"market":"CN","source":"baostock","adjustment":"forward","symbol":"600000.SH","reason":"用户自己填写的观察依据"}`；价格条件将 `reason` 换为 `"condition":"above","target_price":"10.50"`（或 `below`）。这些是输入格式，不是交易推荐。

## 仅用 Docker 在本地部署

全新环境可直接从空库启动（首次构建需要访问镜像源和包仓库）：

```bash
docker compose -f compose.yaml -f deploy/compose.local.yaml up -d --build --wait
```

访问 http://127.0.0.1:8188 。镜像启动先执行 Alembic，再启动控制台；MySQL 持久卷保存数据，容器内不含个人 `.env`、账户数据或导入源。默认是空证券库和空账户，需按自己的使用范围导入/同步。宿主机仍只开放 loopback；不要把账户控制台直接接到公网域名。如果该端口已有宿主进程，请先停止旧的控制台再启动容器。

券商配置由你在本地显式添加到服务环境；默认容器不配置券商凭证。富途 OpenD 集成使用上面的宿主机安装路径，或自行安装对应可选依赖并配置网关。详细部署与公开边界见 [部署文档](docs/architecture/deployment.md)。

## 公共展示包（与个人控制台分离）

为后续 `stock.zhiyu.hk` 展示准备了独立静态导出。选择你有权公开的数据、明确标的与交易日，输出目录必须为空：

```bash
uv run tradeguard public export --market CN --source baostock --date 2026-10-22 \
  --symbol 600000.SH --symbol 600519.SH --output dist/public-2026-10-22
python3 -m http.server 8191 --bind 127.0.0.1 --directory dist/public-2026-10-22
```

示例日期需要替换成已存行情日。导出文件只有独立的 `index.html`：白名单字段包含公开证券名称、行业、同源历史行情、当日策略名称与扫描计数；不含账户、持仓、条件单、自选/研究备注、个人规则、原话或内部运行日志。页面保留日期、来源、复权和缺口，提供项目关注与本地部署入口；不调用个人 API，也不需要运行 Python/MySQL。当前只提供包和本地预览，没有自动上传或修改线上站点。

源码公开前，仍需解决 [provenance](docs/provenance.md) 中记录的来源权利和项目许可证。当前改动未复制 OpenStock 代码，也未修改仓库可见性。

## 本地 Agent 每日研究 Top 5

Codex 负责分析，控制台展示详细依据。先读取指定交易日、来源和复权的全部命中，冻结证据包；Agent 比较候选并写明排序方法、理由、反证、失效条件和下一步，提交后首页展示同一报告。缺乏证据时允许少于五只或空名单。不会自动调用付费模型或创建定时任务。

```bash
uv run tradeguard research prepare --market CN --source baostock --adjustment forward --date 2026-10-22 > private/evidence.json
uv run tradeguard research shortlist-schema
# 由本地 Agent 阅读证据、按 schema 编写 private/shortlist.json
uv run tradeguard research shortlist-save --file private/shortlist.json
uv run tradeguard research shortlist --market CN --source baostock --adjustment forward
```

日期是示例。早晨任务应明确选择最近已完成、已扫描的交易日，不能遇休市仍机械减一天。流程与研究框架见 [每日研究 Top 5](skills/stock-analyst/references/daily-top5.md)。扫描引用校验保证股票属于证据包，不保证自然语言推理正确；个人买入资格仍需显式规则、新鲜持仓和拟交易检查。
