# 本地私有环境与公共展示

## 个人使用

Python CLI 与 FastAPI 共用业务服务，账户控制台只绑定本机。原生启动见 README；容器启动使用 `docker compose -f compose.yaml -f deploy/compose.local.yaml up -d --build --wait`。基础 compose 提供 MySQL 8.4，叠加文件提供控制台。容器内部 uvicorn 监听 0.0.0.0，宿主端口明确映射到 127.0.0.1:8188；MySQL 只映射 127.0.0.1:53306。CLI 的非 loopback 拒绝规则继续保留。

镜像分两阶段构建：Node 22 构建 TypeScript/React，Python 3.12 / Debian trixie（满足 Longbridge Linux wheel 的 glibc 下限）安装锁定 Python 依赖及 market/longbridge extras，复制编译资源与 Alembic 迁移。启动时先迁移独立运行库，成功后再启动 HTTP。运行用户不是 root。构建上下文排除 `.env`、private、data、logs、Git、虚拟环境和 node_modules；镜像没有个人配置，默认空库不自动导入示例或任何账户。

同一端口的本机 Origin 可写，额外允许明确的前端开发 Origin；外部网页和其他任意本机端口的 Origin 被拒绝。默认账户控制台没有公网鉴权、租户隔离或远程安全承诺。不要把它直接作为 stock.zhiyu.hk 的上游。

## 私有状态

- watch_item：个人研究队列；每个证券/来源/复权唯一，原因可编辑，保留加入时间及关联扫描。删除只删除自选，不改账户、行情或历史提醒。
- price_alert：独立价格条件；Decimal 目标价，达到条件后停用。删除接口是停用，不删除触发历史。
- notification：去重提醒和已读状态。相同价格条件只生成一条；新信号按自选和扫描批次去重；快照按账户和原观察去重。

提醒评估只读缓存和快照，可以由页面、CLI 或用户自己的调度执行。没有常驻检查器或外部发送服务。没有新证据时不重复产生提醒；不刷新原始观察时间。

## 公共展示

公共站从 `public export` 生成单个 HTML，由 `public_site/export.py` 正向构造固定市场字段。仅从 security、daily_bar、scan_summary、scan_result 取明确公开字段，不调用私有 workspace report、不序列化完整 ORM、JSON 元数据或 research/portfolio/discipline 状态。标的上限 50、每股最多 60 根日线，市场、来源、复权、交易日显式传入，拒绝未来日期和混市场标的。HTML 数据转义 `<>&`；页面用 textContent 填文本，防止名称中的 HTML 变为脚本。

导出要求新的空目录，避免误把其他文件一起部署。可以用任意静态服务器预览/托管，不需要生产数据库、账户密钥或个人 API。stock.zhiyu.hk 是后续部署目标；本阶段仅完成独立包，不改线上 DNS、服务或仓库公开状态。市场数据的再分发权由公开者核对；源码许可证仍依 provenance 处理。

## 验证

集成测试为每个测试创建独立临时 MySQL 数据库，经 Alembic 从空库升级，结束后删除；不 truncate 运行库。CI 使用合成数据，先构建前端再测试，避免 Vite 清理 dist/assets 与 FastAPI 挂载发生竞争。浏览器验收也使用独立合成账户，不写真实账户。公开导出测试向私有表、元数据和内部日志放入哨兵，验证输出没有这些字段，并验证 HTML 注入转义。
