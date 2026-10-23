# 本地 Codex 每日研究 Top 5

目标：给用户一个有依据的研究优先级；聊天展示简要结论，TradeGuard 保存复杂证据。不是自动下单或收益预测。该流程由本地 Agent 执行，不在 Web 服务内调用模型。

## 执行

1. 检查 `uv run tradeguard doctor`。确认市场、来源、复权和已收盘交易日。每日早上 7 点通常分析前一个已完成交易日，但不能机械减一天（周末/休市）；读取当前来源实际扫描日期，再明确传日期。缺最新扫描时说明缺口；刷新行情需显式授权，不为凑数据跨源或拉全市场。
2. `uv run tradeguard research prepare --market CN --source SOURCE --adjustment forward --date YYYY-MM-DD > private/evidence.json`。读取 JSON envelope 的状态，再读取 data。证据包冻结所有命中，不只前 20 名；保留扫描批次、参数、覆盖、市场环境和策略原始数值。历史包是当前读取的保存记录，不是保证当时可获得的回测快照。
3. 按下面的方法比较整个候选池。技术证据能得出的只是技术研究名单；若要声称估值便宜、业绩催化或政策受益，必须另查原始披露并提供来源，不能从行业名称推断。当前 shortlist 合约只验证扫描引用，不承载或核验外部财务断言。
4. `uv run tradeguard research shortlist-schema` 获取严格提交结构。创建被忽略的 `private/shortlist.json`，包含 evidence_pack_id、author、summary、methodology、picks（最多五只）、alternatives（未入选者与理由）。每只包括 symbol、thesis、evidence_ids（该股票的扫描引用）、risks、invalidation、next_step。不足五只必须给 abstention_reason；零只也可以。
5. `uv run tradeguard research shortlist-save --file private/shortlist.json`。它核验股票与证据引用并保存不可变报告，不会验证自然语言推理为真。通过 `research shortlist --market CN --source SOURCE --adjustment forward` 复读并核对；首页显示相同报告。复扫不修改旧报告，新的分析应另存版本。
6. 聊天输出：日期/来源、市场判断、最多五只及各一句理由、共同风险、下一步。无需在聊天里贴完整 JSON。

## 分析框架 technical-review-v1

这是一套显式研究方法，不是用户的交易纪律，不擅自变成个人仓位/买卖阈值。

- 先看环境：基准缺失保持未知；弱势环境下单股突破更需延续确认。partial 只表示已扫描子集内的名单，不能称全 A 股最优。
- 信号结构：区分趋势/动量与突破/量能。布林带与箱体同时命中经常相关；共振数量不是独立证据数量，更不是概率。
- 位置与代价：如有同复权 box_top/MA20，计算收盘偏离比例，并标注是自证据推导。贴近突破位可能更容易定义失效，但也可能是假突破；大幅偏离时关注追涨和回撤风险。缺关键数值不编造入场、止损、ATR 或盈亏比。
- 量能：量比反映参与度而非必然持续性，极端放量也可能是分歧；不能直接给高量比加分。
- 行业：用已有 sector_strength 比较相对强弱，缺值不填 0。保留同业集中风险；允许有理由选择同业两只，不凑机械分散。
- 比较：说明为什么优于至少一只相近备选；允许低共振但结构不同的候选入选，也允许不满五只。不要创造未经回测的胜率、目标收益或“AI 综合 95 分”。
- 反证与失效：每只都解释什么观察会削弱论点；计划观察位不等于券商止损单，也不等于用户应买卖的价格。
- 决策边界：个人买入/加仓必须另给 account、版本规则与具体意图，调用 trading-discipline。缺新鲜资产、持仓或保护单证据保留 needs_input；研究报告的排序不能覆盖该结果。

默认只有扫描证据时，明确写“公告/基本面/估值未核验”。不得为提升说服力捏造最新新闻、资金流、主力行为、北向持仓或交易权限。
