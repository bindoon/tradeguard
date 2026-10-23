import { useEffect, useState } from "react";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import {
  decisionLabel,
  loadWorkspace,
  refreshNotices,
  regimeLabel,
  Workspace,
} from "./workspaceApi";
import { STRATEGY_MAP } from "./strategies";
import WatchButton from "./WatchButton";
import ResearchShortlist from "./ResearchShortlist";
import EmptyMarket from "./EmptyMarket";
export default function HomePage(props: SelectionNavProps) {
  const { market, source, adjustment, info } = useMarket();
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    setLoading(true);
    if (!source) {
      setLoading(false);
      return;
    }
    loadWorkspace()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [market, source, adjustment, tick]);
  const report = data?.report;
  const currency = market === "CN" ? "CNY" : market === "US" ? "USD" : "HKD";
  const changes = report?.changes_vs_previous_day;
  const availableScans = (info?.sources || [])
    .filter(
      (s) => s.scan_count > 0 && (s.source !== source || s.adjustment !== adjustment),
    )
    .sort((a, b) =>
      (b.latest_scan_date || "").localeCompare(a.latest_scan_date || ""),
    );
  const currentCache = info?.sources.find(
    (s) => s.source === source && s.adjustment === adjustment,
  );
  const adjustmentLabel = (value: string) =>
    value === "forward" ? "前复权" : value === "backward" ? "后复权" : "不复权";
  return (
    <SelectionShell {...props} currentSection="home">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs tracking-widest text-emerald-300">
            我的研究与决策
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-white">每日工作台</h1>
          <p className="mt-2 text-sm text-slate-400">
            查看最近一次扫描选出的股票，点开候选查看图表与命中原因。
          </p>
        </div>
        <button
          className="tg-button"
          disabled={!source || busy}
          onClick={async () => {
            setBusy(true);
            try {
              await refreshNotices();
              setTick((t) => t + 1);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "正在评估…" : "刷新缓存提醒"}
        </button>
      </header>
      {loading && <p className="tg-muted">正在整理当前市场工作台…</p>}
      {error && (
        <p role="alert" className="tg-panel text-red-300">
          {error}
          <button
            className="ml-4 underline"
            onClick={() => setTick((t) => t + 1)}
          >
            重试
          </button>
        </p>
      )}
      {!loading && !source && <EmptyMarket />}
      {source && !loading && !error && !report && availableScans.length > 0 && (
        <section
          className="tg-panel border-amber-400/40"
          aria-label="已有扫描可查看"
        >
          <h2 className="tg-title">本地已有扫描，当前选中的来源没有记录</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            当前是 {source} · {adjustmentLabel(adjustment)}，缓存截止 {currentCache?.max_date || "未知"}。
            切换到下面的来源即可查看已保存的候选，无需重新扫描。
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            {availableScans.map((s) => (
              <button
                key={s.source + s.adjustment}
                className="tg-primary"
                onClick={() =>
                  openPath(scopedPath("/", {
                    source: s.source, adjustment: s.adjustment,
                  }))
                }
              >
                查看 {s.source} · {adjustmentLabel(s.adjustment)} · {s.latest_scan_date} · {s.scan_count} 次扫描 →
              </button>
            ))}
          </div>
        </section>
      )}
      {source && !loading && !error && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              [
                "最近扫描",
                report?.trade_date || "尚无扫描",
                report
                  ? `${report.source} · ${report.status === "success" ? "完整" : "部分完成"}`
                  : "选择扫描日期后执行缓存扫描",
              ],
              [
                "市场状态",
                report
                  ? regimeLabel[report.market_regime] || "证据不足"
                  : "未知",
                report?.market_regime === "bear"
                  ? "基准处于弱势，先复核风险再研究候选"
                  : "依据同源基准；缺少基准时保持未知",
              ],
              [
                "策略命中 / 共振",
                report
                  ? `${report.counts.hits} / ${report.counts.resonance}`
                  : "—",
                "扫描候选，不直接等于买入建议",
              ],
              [
                "持仓待处理",
                data
                  ? String(
                      data.position_reviews.filter(
                        (r) => r.decision !== "observe",
                      ).length,
                    )
                  : "—",
                "过期观察、退出复核与证据缺口",
              ],
            ].map(([label, value, note]) => (
              <section className="tg-panel" key={label}>
                <p className="text-xs text-slate-400">{label}</p>
                <p className="my-3 text-2xl font-semibold text-white">
                  {value}
                </p>
                <p className="text-xs leading-5 text-slate-500">{note}</p>
              </section>
            ))}
          </div>
          <details className="tg-panel">
            <summary className="cursor-pointer font-medium text-slate-200">持仓复核 · {data?.position_reviews.filter((r) => r.decision !== "observe").length || 0} 项待处理（展开查看）</summary>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="tg-title">先看我的持仓 · 买卖复核</h2>
              <button
                className="text-sm text-cyan-300"
                onClick={props.onPortfolio}
              >
                全部账户 →
              </button>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              根据当前持仓观察与已记录的退出计划复核。现金和资产按账户、币种查看；不合并不同币种。日线收盘触及计划不证明券商已成交。
            </p>
            {!data?.position_reviews.length ? (
              <p className="tg-muted">
                当前市场没有已保存的股票持仓，可先导入真实账户。
              </p>
            ) : (
              <div className="mt-4 grid gap-3 xl:grid-cols-2">
                {data.position_reviews.map((r, i) => (
                  <article
                    key={`${r.account_label}-${r.symbol}-${i}`}
                    className="rounded-xl border border-slate-700 bg-slate-950/50 p-4"
                  >
                    <div className="flex flex-wrap justify-between gap-2">
                      <button
                        disabled={!r.symbol}
                        onClick={() =>
                          r.symbol &&
                          openPath(
                            scopedPath(
                              "/stock/" + encodeURIComponent(r.symbol),
                            ),
                          )
                        }
                        className="font-semibold text-slate-100"
                      >
                        {r.name || r.symbol || r.account_label}
                        {r.symbol && (
                          <span className="ml-2 text-xs text-slate-500">
                            {r.symbol} · {r.account_label}
                          </span>
                        )}
                      </button>
                      <span
                        className={`text-xs ${r.decision === "review_exit" ? "text-amber-300" : r.decision === "needs_input" ? "text-orange-300" : "text-slate-400"}`}
                      >
                        {decisionLabel[r.decision]}
                      </span>
                    </div>
                    {r.close && (
                      <p className="mt-2 text-xs text-slate-400">
                        {r.price_date} 缓存收盘 {r.close} {r.currency} ·
                        持仓观察{" "}
                        {r.observed_at
                          ? new Date(r.observed_at).toLocaleString("zh-CN")
                          : "未知"}
                      </p>
                    )}
                    <ul className="mt-3 space-y-1 text-sm leading-6 text-slate-400">
                      {r.reasons.map((reason) => (
                        <li key={reason}>· {reason}</li>
                      ))}
                    </ul>
                    {r.symbol && (
                      <button
                        className="mt-3 text-xs text-cyan-300"
                        onClick={() =>
                          openPath(
                            scopedPath(
                              "/stock/" + encodeURIComponent(r.symbol!),
                            ),
                          )
                        }
                      >
                        查看图表、计划与买入检查 →
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
          </details>
          <ResearchShortlist report={data?.recommendation || null} latestScanDate={report?.trade_date} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(280px,1fr)]">
            <section className="tg-panel">
              <div className="flex justify-between">
                <h2 className="tg-title">{report ? `${report.trade_date} 策略候选` : "策略候选"}</h2>
                <button
                  className="text-sm text-cyan-300"
                  onClick={() =>
                    openPath(
                      scopedPath(report ? "/scan/" + report.run_id : "/scan"),
                    )
                  }
                >
                  扫描明细 →
                </button>
              </div>
              {report && (
                <p className="mt-3 text-xs leading-6 text-slate-400">
                  {report.source} · {adjustmentLabel(report.adjustment)} · 已扫描 {report.counts.scanned.toLocaleString()} / {report.counts.universe.toLocaleString()} 个标的，
                  {report.counts.hits} 只命中，以下展示共振排序前 {Math.min(8, report.top_resonance.length)} 只。
                  {report.status !== "success" && "本次部分完成，完整情况见扫描明细。"}
                </p>
              )}
              {!report ? (
                <p className="tg-muted">
                  本市场、来源和复权尚无扫描结果。可以在每日扫描中选择已保存行情执行。
                </p>
              ) : !report.top_resonance.length ? (
                <p className="tg-muted">本次扫描没有策略命中。</p>
              ) : (
                <div className="mt-3 divide-y divide-slate-800">
                  {report.top_resonance.slice(0, 8).map((p) => (
                    <article key={p.symbol} className="py-4">
                      <div className="flex flex-wrap justify-between gap-3">
                        <button
                          className="text-left font-semibold text-slate-100"
                          onClick={() =>
                            openPath(
                              scopedPath(
                                "/stock/" + encodeURIComponent(p.symbol),
                                { endDate: report.trade_date },
                              ),
                            )
                          }
                        >
                          {p.name || p.symbol}{" "}
                          <span className="text-xs font-normal text-slate-500">
                            {p.symbol} · {p.close} {currency}
                          </span>
                        </button>
                        <span className="text-sm text-emerald-300">
                          共振 {p.resonance_count}
                        </span>
                      </div>
                      <p className="mt-2 text-xs text-slate-400">
                        {p.strategies_hit
                          .map((s) => STRATEGY_MAP[s]?.title || s)
                          .join(" · ")}
                      </p>
                      {p.reasons[0] && (
                        <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">
                          {p.reasons[0].split("。：")[0]}
                        </p>
                      )}
                      <div className="mt-3">
                        <WatchButton symbol={p.symbol} runId={report.run_id} />
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
            <div className="space-y-4">
              <section className="tg-panel">
                <div className="flex justify-between">
                  <h2 className="tg-title">我的自选</h2>
                  <button
                    className="text-sm text-cyan-300"
                    onClick={() => openPath(scopedPath("/watchlist"))}
                  >
                    管理 →
                  </button>
                </div>
                {!data?.watchlist.length ? (
                  <p className="tg-muted">
                    从候选或个股页加入自选，记录为什么关注。
                  </p>
                ) : (
                  data.watchlist.slice(0, 5).map((w) => (
                    <button
                      key={w.id}
                      onClick={() =>
                        openPath(
                          scopedPath("/stock/" + encodeURIComponent(w.symbol)),
                        )
                      }
                      className="mt-3 block w-full rounded-lg bg-slate-950/50 p-3 text-left text-sm text-slate-200"
                    >
                      {w.name || w.symbol}
                      <span className="float-right text-xs text-slate-400">
                        {w.close || "暂无价格"}
                      </span>
                      <p className="mt-2 truncate text-xs text-slate-500">
                        {w.reason || "尚未填写观察原因"}
                      </p>
                    </button>
                  ))
                )}
              </section>
              <section className="tg-panel">
                <div className="flex justify-between">
                  <h2 className="tg-title">待处理提醒</h2>
                  <button
                    className="text-sm text-cyan-300"
                    onClick={() => openPath(scopedPath("/alerts"))}
                  >
                    查看 →
                  </button>
                </div>
                {!data?.notifications.some((n) => !n.read) ? (
                  <p className="tg-muted">
                    暂无未读提醒。点击刷新评估已保存的行情与快照。
                  </p>
                ) : (
                  data.notifications
                    .filter((n) => !n.read)
                    .slice(0, 5)
                    .map((n) => (
                      <p
                        key={n.id}
                        className="mt-3 border-l-2 border-amber-400/50 pl-3 text-sm leading-6 text-slate-300"
                      >
                        {n.title}
                      </p>
                    ))
                )}
              </section>
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <section className="tg-panel">
              <h2 className="tg-title">与前一次同源扫描相比</h2>
              {!changes?.previous_date ? (
                <p className="tg-muted">暂无同来源、同复权的可比历史。</p>
              ) : (
                <>
                  <p className="mt-3 text-xs text-slate-500">
                    {changes.previous_date} → {report?.trade_date} · {source}
                  </p>
                  <p className="mt-3 text-sm text-slate-300">
                    新增命中 {changes.new_symbol_count} · 消失{" "}
                    {changes.dropped_symbol_count} · 命中变化{" "}
                    {changes.hit_delta}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {changes.new_symbols.slice(0, 8).map((p) => (
                      <button
                        className="tg-tab text-emerald-300"
                        key={p.symbol}
                        onClick={() =>
                          openPath(
                            scopedPath(
                              "/stock/" + encodeURIComponent(p.symbol),
                            ),
                          )
                        }
                      >
                        + {p.name || p.symbol}
                      </button>
                    ))}
                  </div>
                  <p className="mt-3 text-xs text-slate-500">
                    扫描覆盖不同或部分完成时，新增/消失也可能由数据缺口造成。
                  </p>
                </>
              )}
            </section>
            <section className="tg-panel">
              <h2 className="tg-title">行业强度</h2>
              {!report?.sector_strength_ranking.length ? (
                <p className="tg-muted">暂无行业记录。</p>
              ) : (
                report.sector_strength_ranking.slice(0, 6).map((s) => (
                  <div
                    className="mt-3 flex justify-between gap-3 text-sm"
                    key={s.sector}
                  >
                    <span className="truncate text-slate-300">{s.sector}</span>
                    <span className="shrink-0 text-slate-400">
                      {s.strength === null ? "强度未知" : s.strength.toFixed(2)}{" "}
                      · {s.hit_count} 命中
                    </span>
                  </div>
                ))
              )}
            </section>
          </div>
          <section className="tg-panel">
            <h2 className="tg-title">最近的个人纪律检查</h2>
            {!data?.recent_checks.length ? (
              <p className="tg-muted">
                打开个股页，选择明确的个人规则版本和账户，填写拟交易后检查。没有默认替你选定的个人纪律。
              </p>
            ) : (
              data.recent_checks.slice(0, 5).map((c) => (
                <div
                  key={c.id}
                  className="mt-3 flex flex-wrap justify-between gap-2 text-sm text-slate-300"
                >
                  <button
                    onClick={() =>
                      openPath(
                        scopedPath("/stock/" + encodeURIComponent(c.symbol)),
                      )
                    }
                  >
                    {c.symbol}
                  </button>
                  <span>
                    {decisionLabel[c.result.decision] || c.result.decision} ·{" "}
                    {new Date(c.created_at).toLocaleString("zh-CN")}
                  </span>
                </div>
              ))
            )}
          </section>
        </>
      )}
    </SelectionShell>
  );
}
