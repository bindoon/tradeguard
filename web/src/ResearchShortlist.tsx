import { Recommendation } from "./workspaceApi";
import { openPath, scopedPath } from "./MarketContext";

export default function ResearchShortlist({ report, latestScanDate }: {
  report: Recommendation | null; latestScanDate?: string;
}) {
  if (!report) return <section className="tg-panel">
    <h2 className="tg-title">每日研究 Top 5</h2>
    <p className="tg-muted">尚无本地 Agent 保存的研究结论。下方是原始扫描候选；Codex 完成证据分析并保存后，这里展示排序、理由、风险和失效条件。</p>
  </section>;
  return <section className="tg-panel">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="tg-title">{report.trade_date} 研究优先级 · Top {report.picks.length}</h2>
      <span className="text-xs text-slate-400">{report.author} · {new Date(report.created_at).toLocaleString("zh-CN")}</span>
    </div>
    <p className="mt-3 text-sm leading-7 text-slate-200">{report.summary}</p>
    <p className="mt-2 text-xs text-amber-300">技术研究名单 · 买入资格待个人规则与新鲜持仓核验{report.scan_status !== "success" && " · 扫描部分完成"}</p>
    {latestScanDate && latestScanDate > report.trade_date && <p role="status" className="mt-2 text-sm text-amber-300">已有更新扫描（{latestScanDate}），此报告仍基于 {report.trade_date} 的证据。</p>}
    {report.picks.map((p) => <article key={p.symbol} className="mt-4 border-t border-slate-700 pt-4">
      <button className="font-semibold text-cyan-300" onClick={() => openPath(scopedPath("/stock/" + encodeURIComponent(p.symbol), { endDate: report.trade_date }))}>
        {p.rank}. {p.evidence.name || p.symbol} · {p.symbol}
      </button>
      <p className="mt-2 text-sm leading-7 text-slate-200">{p.thesis}</p>
      <p className="mt-2 text-sm leading-6 text-amber-200">风险：{p.risks.join("；")}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">失效条件：{p.invalidation}</p>
      <p className="mt-2 text-sm leading-6 text-slate-400">下一步：{p.next_step}</p>
      <details className="mt-3 text-xs leading-6 text-slate-400"><summary className="cursor-pointer text-cyan-300">查看原始扫描证据</summary>
        <p>{report.trade_date} · {report.scope.source} · {report.scope.adjustment} · 共振 {p.evidence.resonance_count} · 缓存收盘 {p.evidence.close} {report.scope.market === "CN" ? "CNY" : report.scope.market === "US" ? "USD" : "HKD"} · 行业相对强度 {p.evidence.sector_strength ?? "未知"}</p>
        {p.evidence.reasons.map((r) => <p key={r}>{r}</p>)}
        <details className="mt-2"><summary className="cursor-pointer">完整策略指标</summary><pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-slate-950 p-3">{JSON.stringify(p.evidence.strategy_details, null, 2)}</pre></details>
        <p className="break-all">引用：{p.evidence_ids.join("、")}</p>
      </details>
    </article>)}
    {report.abstention_reason && <p className="tg-muted">未凑足五只：{report.abstention_reason}</p>}
    <details className="mt-4 text-xs leading-7 text-slate-400"><summary className="cursor-pointer">备选与证据边界</summary>
      <p>排序方法：{report.methodology}</p>
      {report.alternatives.map((a) => <p key={a.symbol}>{a.symbol}：{a.reason}</p>)}
      {report.limitations.map((l) => <p key={l}>{l}</p>)}
      <p>系统核验股票与证据引用关系；文字推理由报告作者负责，未自动核验每一句判断。</p>
    </details>
  </section>;
}
