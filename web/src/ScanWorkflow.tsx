import { useMarket } from "./MarketContext";
import { ScanSummary } from "./types";
import { DAILY_STRATEGIES, STRATEGY_MAP } from "./strategies";

export default function ScanWorkflow({ summary }: { summary?: ScanSummary }) {
  const { market, info } = useMarket();
  const config = summary?.filterConfig;
  const value = (
    key: keyof NonNullable<ScanSummary["filterConfig"]>,
    fallback: string,
  ) => (summary ? config?.[key] : info?.filter_defaults?.[fallback]);
  const checks: string[] = [];
  if (value("filterSt", "filter_st")) checks.push("剔除 ST / *ST 股票");
  if (value("filterSuspended", "filter_suspended"))
    checks.push("剔除停牌或零成交量股票");
  if (value("filterNewStock", "filter_new_stock"))
    checks.push(
      `剔除上市不满 ${value("minListedDays", "min_listed_days") ?? "未记录"} 天的新股`,
    );
  if (value("filterLiquidity", "filter_liquidity")) {
    const amount = value("minAvgVolume5d", "min_avg_amount");
    checks.push(
      `近 5 日日均成交额 ≥ ${typeof amount === "number" ? (amount >= 100_000_000 ? `${amount / 100_000_000} 亿` : amount >= 10_000 ? `${amount / 10_000} 万` : amount.toLocaleString("zh-CN")) : "未记录"} ${market === "CN" ? "CNY" : market === "US" ? "USD" : "HKD"}`,
    );
  }
  if (value("filterLimit", "filter_limit")) {
    const limit = value("limitPct", "limit_pct");
    checks.push(
      `剔除触及涨跌幅阈值（主板 ${typeof limit === "number" ? (limit * 100).toFixed(1) + "%" : "未记录"}，分板块计算）`,
    );
  }
  const strategies = summary
    ? summary.scanStrategies || []
    : DAILY_STRATEGIES.map((s) => s.name);
  const benchmark =
    summary?.benchmark ||
    (market === "CN" ? "000001.SH" : market === "US" ? "SPY.US" : "02800.HK");
  return (
    <section
      className="rounded-xl border border-slate-200 bg-white/60 p-4 sm:p-5"
      aria-label="扫描流程"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">扫描流程</h2>
        <p className="text-xs text-slate-500">
          {summary
            ? `${summary.scanDate} 批次规则，其他批次以各自明细为准`
            : "当前市场默认流程；历史记录使用各自保存的规则"}
        </p>
      </div>
      <div className="grid items-start gap-3 lg:grid-cols-3">
        <details className="rounded-lg border border-slate-200/70 bg-slate-50/40 p-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-900">
            <span className="mr-2 text-emerald-700">01</span>市场环境
            <p className="mt-2 text-xs font-normal leading-5 text-slate-500">
              基准 MA20 判断牛市 / 震荡 / 熊市
            </p>
          </summary>
          <div className="mt-3 space-y-2 border-t border-slate-200 pt-3 text-xs leading-5 text-slate-500">
            <p>基准：{benchmark}</p>
            <p>
              <b className="text-emerald-700">牛市</b>：收盘 &gt; MA20，且 MA20
              近 5 日斜率为正。
            </p>
            <p>
              <b className="text-amber-700">震荡</b>：未同时满足牛市或熊市条件。
            </p>
            <p>
              <b className="text-red-600">熊市</b>：收盘 &lt; MA20，且 MA20 近 5
              日斜率为负。
            </p>
            <p>基准不足时，环境与行业相对强度保持未知。</p>
          </div>
        </details>
        <div className="rounded-lg border border-slate-200/70 bg-slate-50/40 p-4">
          <h3 className="text-sm font-medium text-slate-900">
            <span className="mr-2 text-emerald-700">02</span>初筛股票池
          </h3>
          <p className="mt-2 text-xs text-slate-500">进入策略前的过滤规则</p>
          <ul className="mt-3 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">
            {checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
          {!checks.length && (
            <p className="mt-3 text-xs text-slate-500">
              {summary
                ? "该批次未记录已启用的过滤项；查看明细核对。"
                : "正在读取当前市场规则…"}
            </p>
          )}
          <p className="mt-2 text-xs leading-5 text-slate-500">
            缺当日行情或历史不足，另记缺口。
          </p>
        </div>
        <details className="rounded-lg border border-slate-200/70 bg-slate-50/40 p-4">
          <summary className="cursor-pointer text-sm font-medium text-slate-900">
            <span className="mr-2 text-emerald-700">03</span>策略扫描
            <p className="mt-2 text-xs font-normal leading-5 text-slate-500">
              {strategies.length
                ? `${strategies.length} 个策略打标，记录共振数`
                : "该批次未记录策略清单"}
            </p>
          </summary>
          <ul className="mt-3 space-y-3 border-t border-slate-200 pt-3 text-xs leading-5 text-slate-500">
            {strategies.map((name) => (
              <li key={name}>
                <b className="text-slate-700">
                  {STRATEGY_MAP[name]?.title || name}
                </b>
                <p>{STRATEGY_MAP[name]?.description || "策略说明尚未记录"}</p>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </section>
  );
}
