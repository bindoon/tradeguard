import { useEffect, useState } from "react";
import { apiFetch } from "./api";

interface Playbook {
  title: string;
  report_id: string;
  created_at: string;
  sources: { document: string; version: string; sha256: string }[];
  reminders: string[];
  sections: { title: string; items: string[] }[];
  notes: string[];
}

export default function PortfolioPlaybook() {
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    apiFetch<Playbook | null>("/api/discipline/playbook")
      .then((data) => { if (!cancelled) setPlaybook(data); })
      .catch((e) => { if (!cancelled) setError((e as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    const refresh = () => setRevision((value) => value + 1);
    window.addEventListener("workspace-updated", refresh);
    return () => {
      cancelled = true;
      window.removeEventListener("workspace-updated", refresh);
    };
  }, [revision]);
  return (
    <section className="rounded-2xl border border-emerald-400/30 bg-white p-5" aria-label="我的策略与纪律">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-emerald-700">我的策略与纪律 · 每次看持仓先读一遍</h2>
        <span className="text-xs text-slate-500">个人手册提醒</span>
      </div>
      {loading ? <p className="mt-3 text-sm text-slate-500">正在读取已保存的个人手册…</p>
        : error ? <p role="alert" className="mt-3 text-sm text-amber-700">个人手册读取失败：{error}<button className="ml-3 underline" onClick={() => setRevision((v) => v + 1)}>重试</button></p>
        : !playbook ? <p className="mt-3 text-sm leading-6 text-slate-500">尚未保存个人手册摘要。告诉 Agent 你的策略文件位置，将仓位、分批买卖、止盈止损规则导入后，这里会持续展示。未导入时不套用示例比例。</p>
        : <>
          <p className="mt-2 text-xs text-slate-500">{playbook.title} · 保存于 {new Date(playbook.created_at).toLocaleString("zh-CN")}</p>
          <ul className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {playbook.reminders.map((item, i) => <li key={i} className="rounded-lg border border-amber-400/20 bg-amber-500/5 px-3 py-2 text-sm font-medium leading-6 text-amber-700">{item}</li>)}
          </ul>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {playbook.sections.map((section, i) => <article key={i} className="rounded-xl border border-slate-200 bg-slate-50/40 p-4">
              <h3 className="font-medium text-slate-900">{section.title}</h3>
              <ul className="mt-2 list-disc space-y-2 pl-4 text-sm leading-6 text-slate-600">
                {section.items.map((item, index) => <li key={index} className="whitespace-pre-line">{item}</li>)}
              </ul>
            </article>)}
          </div>
          {playbook.notes.length > 0 && <div className="mt-4 space-y-2 border-t border-slate-200 pt-3 text-xs leading-6 text-amber-700/80">{playbook.notes.map((note, i) => <p key={i}>{note}</p>)}</div>}
          <details className="mt-3 text-xs text-slate-500">
            <summary className="cursor-pointer text-cyan-700">查看手册来源与版本</summary>
            <ul className="mt-2 space-y-1 break-words">{playbook.sources.map((source, i) => <li key={i}>{source.document} · {source.version}</li>)}</ul>
            <p className="mt-2">摘要版本 {playbook.report_id}。手册更新后需让 Agent 重新导入。这里展示个人计划；实际价格、数量和挂单状态仍以下方持仓记录及券商核验为准。买入检查须另选明确的数值规则版本。</p>
          </details>
        </>}
    </section>
  );
}
