# 美股版分析手册

> 做 美股 分析时读这份。套用 SKILL.md 的四层评分卡，本文件提供美股专属的：宏观/资金面取数、数据源、雷区清单、估值体系、行业模板。
> 把搜索词里的 `[YEAR]` 换成当前年份、`[MONTH]` 换成当前月份（美股搜索建议用英文关键词，命中率更高）。

---

## 一、美股的特殊性（取数前先记住，别把 A股 那套搬过来）

- **不是政策市，是利率市 + 财报市**：宏观第一变量是 **美联储利率/流动性周期**，其次是产业法案（IRA / CHIPS）。
- **机构主导、有效性高**：**不要去"猜庄家/主力"**——这套在美股不适用。资金面要换成可验证的机构信号：13F 持仓、做空比例、ETF 资金流、分析师评级、期权 P/C。
- **财报更透明、更频繁、更结构化**：GAAP + 季报（10-Q）+ 年报（10-K）+ 重大事项（8-K），全部在 SEC EDGAR 公开。→ **财务层可以做得比 A股 版更深**。
- **估值体系更丰富**：别只套 PE/PB，要按行业用 DCF / EV-EBITDA / PEG / FCF / PS+Rule of 40（SaaS）。
- **交易制度**：T+0、无涨跌停、个股期权丰富、盘前盘后交易、财报盘后跳空大。这些影响**进场/止损执行**（属 trading-discipline）。
- **特别注意中概股**：叠加 HFCAA 退市风险 + 中美监管，按"中概雷区"单独加查。

---

## 二、模式一：行业趋势扫描（搜索策略）

按顺序执行，共 4-6 次搜索。

```
搜索1 宏观/利率层（美股最关键）
  "Fed interest rate decision outlook [YEAR][MONTH]" / "FOMC dot plot rate cut expectations"
  "[sector] sector outlook [YEAR] interest rate sensitivity"
  目标：判断当前处于加息/降息/观望周期，哪些板块顺风（成长股对利率敏感）

搜索2 产业法案/政策催化
  "IRA Inflation Reduction Act [sector] beneficiaries [YEAR]"
  "CHIPS Act semiconductor funding [YEAR]" / "[sector] government subsidy policy US [YEAR]"
  目标：找有法案级资金驱动的方向（清洁能源/半导体/基建）

搜索3 机构/资金层（替代 A股 的北向主力）
  "13F filings top hedge fund holdings [sector] Q[x] [YEAR]"
  "ETF fund flows [sector] [YEAR][MONTH]" / "analyst upgrades [sector] [YEAR][MONTH]"
  目标：分别观察季度末持仓、ETF申赎和卖方预期；不能用13F推断本周或昨天机构交易

搜索4 财报季情绪
  "[sector] earnings season Q[x] [YEAR] guidance beats misses"
  目标：财报季是美股最大的短期驱动，看 guidance（指引）比看 EPS 更重要
```

---

## 三、模式二：个股深度分析（搜索策略）

共 6-8 次搜索。

```
搜索1 基本信息：  "[ticker] stock sector market cap business overview" → 定位产业链位置
搜索2 宏观层：    "[sector] industry outlook market size [YEAR]" + "[sector] interest rate sensitivity"
搜索3 竞争层：    "[company] market share competitors moat" + "[sector] market leader"
搜索4 产业链层：  "[sector] supply chain value chain margin distribution" + "[company] pricing power gross margin"
搜索5 财务/估值（先跑 longbridge，再 web_search 补充）：
  longbridge quote SYMBOL.US
  longbridge financial-statement SYMBOL.US --kind ALL
  longbridge financial-report SYMBOL.US --latest
  longbridge valuation-rank SYMBOL.US
  longbridge analyst-estimates SYMBOL.US
  缺口再搜："[ticker] PE PEG EV/EBITDA FCF revenue growth"（SaaS 加 "PS ratio Rule of 40"）；原始披露见第五节 EDGAR
搜索6 机构信号（先跑 longbridge，再 web_search 补充）：
  longbridge investors                    # 活跃机构概览
  longbridge investors <CIK>              # 某机构持仓
  longbridge insider-trades SYMBOL.US
  缺口再搜："[ticker] short interest" + "[ticker] put call ratio"
搜索7 雷区检测：  见第四节
```

---

## 四、美股雷区清单（个股必查，整块替换 A股 雷区）

```
"[company] short seller report [YEAR]"           → 做空机构报告（Muddy Waters/Hindenburg 类），尤其针对中概/小盘
"[ticker] SEC investigation subpoena [YEAR]"     → SEC 调查/传票
"[ticker] stock based compensation SBC dilution" → SBC 过高 / 股权稀释（科技股高发，吃掉 GAAP 利润、稀释股东）
"[company] debt refinancing high leverage [YEAR]" → 高债务再融资风险（利率高企时尤其致命）
"[ticker] revenue recognition accounting concerns" → 收入确认/会计问题
"[ticker] insider selling [YEAR]"                → 内部人抛售
中概股加查：
"[ticker] HFCAA delisting risk PCAOB audit"      → HFCAA 退市风险 + PCAOB 审计底稿
"[ticker] VIE structure China regulatory risk"   → VIE 结构 + 中美监管
```

命中做空报告/SEC 调查/退市风险 → 评级直接压到"回避"或大幅扣分，并在【雷区检测】点名。

---

## 五、数据源（美股）

> **取数原则**：长桥便捷取行情/结构化摘要；关键定量判断直接核对一手披露，无需等长桥失败。来源入口与方法见 [一手数据来源与溯源](data-sources.md)。

### 便捷采集：longbridge CLI

Symbol 格式：`NVDA.US`、`AAPL.US`。完整命令见 `longbridge` skill；常用映射：

```bash
longbridge quote SYMBOL.US
longbridge kline history SYMBOL.US --start YYYY-MM-DD --end YYYY-MM-DD --period day
longbridge financial-statement SYMBOL.US --kind ALL   # 三表 + YoY
longbridge financial-report SYMBOL.US --latest        # 营收/EPS/ROE 等 KPI
longbridge valuation-rank SYMBOL.US                   # PE/PB/PS 行业分位
longbridge analyst-estimates SYMBOL.US                # 分析师一致预期
longbridge news SYMBOL.US                             # 新闻
longbridge filing SYMBOL.US                           # 8-K/10-Q/10-K 等
longbridge insider-trades SYMBOL.US                   # Form 4 内部人交易
longbridge investors                                  # 活跃机构（13F）
longbridge investors <CIK>                            # 某机构持仓明细
```

> 缓存：财报/13F 季度更新，TTL 可较长（天级）；报价 TTL 短（分钟级）。

### 原始证据：SEC EDGAR 与公司 IR

关键财务直接核对 SEC EDGAR 和公司 IR：10-K / 10-Q / 8-K / 13F / Form 4；外资发行人另看20-F/6-K，勿强套季报频率。公司指引与已实现数据分开。
- [EDGAR 官方全文检索页面](https://www.sec.gov/edgar/search/)；程序取数使用下列有官方文档的接口，不把网页内部搜索请求当稳定公开 API。
- 公司提交列表 API：`https://data.sec.gov/submissions/CIK##########.json`
- 结构化财报概念 API：`https://data.sec.gov/api/xbrl/companyconcept/CIK.../us-gaap/...`
- [官方API文档](https://www.sec.gov/edgar/sec-api-documentation)：Submissions 查提交记录，Company Facts 查财务标签；保留 accession、期间、单位和 filed 日期以处理修订及重复标签。请求遵守官方 User-Agent 和访问规则。
- 13F 是季度快照，通常季末后45天内披露，不含股票空头；FINRA未平仓空头与每日卖空成交分开；ETF AUM变化剔除净值/汇率影响后才讨论资金流。
- 宏观与产业定量表优先 Federal Reserve、BLS、BEA、Census、EIA、SIA/WSTS 等原始发布；目录见 `data-sources.md`，媒体用于定位原始报告。

### 兜底：yfinance（长桥未覆盖时）

`pip install yfinance`。期权链、做空比例等 longbridge 缺项时用；**不要作为默认取数方式**。
```python
import yfinance as yf
t = yf.Ticker("NVDA")
t.info                 # 估值倍数、市值、利润率
t.financials / t.balance_sheet / t.cashflow
t.recommendations      # 分析师评级
t.institutional_holders
t.option_chain(date)   # 期权链（算 P/C）
```

### 兜底：FMP / Alpha Vantage / Finnhub（API key）

longbridge + yfinance 仍缺结构化数据时再考虑：
- **FMP**：DCF、analyst estimates
- **Alpha Vantage**：技术指标
- **Finnhub**：新闻情绪

---

## 六、美股估值体系（别只套 PE/PB，按行业选锚）

| 公司类型 | 主估值法 | 说明 |
|---|---|---|
| 成熟盈利（消费/工业） | **PE + PEG**、DCF | PEG<1 偏便宜；DCF 算内在价值 |
| 重资产/高杠杆（电信/能源/并购多） | **EV/EBITDA** | 剔除资本结构差异，比 PE 更可比 |
| 现金流型 | **FCF yield、DCF** | 自由现金流是硬通货，看 FCF/市值 |
| 高成长 SaaS/软件（常未盈利） | **PS + Rule of 40** | Rule of 40 = 营收增速% + 利润率% ≥ 40 为健康；PS 配合增速看 |
| 银行/金融 | PB、ROE | 与 A股 一致 |

关键提醒：
- **看 GAAP 也看 non-GAAP**，但警惕公司用 non-GAAP 把 **SBC（股权激励费用）** 加回美化利润。
- 成长股估值高不等于贵，要结合**增速 + FCF 转正路径**；利率上行时高估值成长股杀估值最狠（呼应宏观层）。

---

## 七、行业搜索模板库（美股）

### 科技 / 半导体（七巨头、AI 算力）
```
宏观：    "AI infrastructure spending [YEAR]" / "CHIPS Act funding recipients"
产业链：  "AI value chain GPU foundry cloud software margin" / "who profits most AI stack"
三高：    "[company] data center GPU market share moat pricing power"
估值：    用 PEG / FCF；超大盘看 EV/EBITDA
```

### 软件 / SaaS
```
宏观：    "software sector interest rate sensitivity [YEAR]" / "enterprise IT spending outlook"
基本面：  "[ticker] ARR net revenue retention Rule of 40" / "SaaS gross margin retention"
估值：    PS + Rule of 40；警惕 SBC 稀释
```

### 清洁能源 / 电动车（IRA 驱动）
```
宏观：    "IRA clean energy tax credit beneficiaries [YEAR]" / "EV demand outlook US [YEAR]"
产业链：  "EV battery supply chain margin" / "solar value chain who profits"
雷区：    现金流烧钱、债务再融资、补贴退坡
```

### 医药 / 生物科技
```
宏观：    "FDA approval pipeline [YEAR]" / "drug pricing policy IRA Medicare negotiation"
基本面：  "[ticker] pipeline phase 3 catalyst" / "biotech cash runway burn rate"
雷区：    临床失败、现金跑道不足、稀释增发
```

### 消费 / 零售
```
宏观：    "US consumer spending outlook [YEAR]" / "retail sales trend inflation impact"
基本面：  "[ticker] same store sales margin pricing power brand"
估值：    PE / EV-EBITDA；看品牌护城河与定价权
```

### 金融 / 银行
```
宏观：    "Fed rate impact bank net interest margin [YEAR]" / "credit cycle outlook"
基本面：  "[ticker] NIM ROE efficiency ratio loan loss provision"
估值：    PB + ROE
```

### 中概股（必加监管/退市维度）
```
监管：    "[ticker] HFCAA delisting PCAOB [YEAR]" / "China ADR regulatory risk VIE"
基本面：  常规四层，但宏观层叠加中美监管与汇率
雷区：    做空机构报告、VIE、退市风险（见第四节）
```
