import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import { useMarket } from "./MarketContext";
import { fetchScanSummaries } from "./api";
import { ScanSummary } from "./types";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import ScanWorkflow from "./ScanWorkflow";
import { groupScanHistory } from "./scanHistory";

interface Props extends SelectionNavProps {
  onBack: () => void;
  onSelectDate: (date: string, source?: string, adjustment?: string) => void;
}
const STATUS: Record<string, string> = {
  success: "已完成",
  partial: "部分完成",
  running: "扫描中",
  queued: "排队中",
  failed: "失败",
  stale: "已中断",
};
const REGIME: Record<string, string> = {
  bull: "牛市",
  bear: "熊市",
  neutral: "震荡",
  unknown: "环境未知",
};
const count = (value?: number | null) =>
  typeof value === "number" ? value.toLocaleString("zh-CN") : "—";

export default function ScanPage({ onBack, onSelectDate, ...nav }: Props) {
  const { market, adjustment, info } = useMarket();
  const [summaries, setSummaries] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [historyDate, setHistoryDate] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setSummaries([]);
    setHistoryDate("");
    fetchScanSummaries(true)
      .then((rows) => {
        if (!cancelled)
          setSummaries(
            [...rows].sort(
              (a, b) =>
                b.scanDate.localeCompare(a.scanDate) ||
                (b.executionDate || "").localeCompare(a.executionDate || ""),
            ),
          );
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [market, adjustment, refresh]);
  const days = groupScanHistory(summaries);
  const historyDates = days.map((day) => day.date);
  const visible = historyDate
    ? days.filter((day) => day.date === historyDate)
    : days;
  return (
    <SelectionShell
      currentSection="scan"
      {...nav}
      onHome={nav.onHome ?? onBack}
    >
      <div className="space-y-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              aria-label="返回工作台"
              onClick={onBack}
              className="tg-button p-2"
            >
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div>
              <h1 className="text-xl font-semibold text-slate-900">
                每日扫描记录
              </h1>
              <p className="mt-1 text-xs text-slate-500">
                {info?.label || market} · {historyDates.length} 个交易日 · 共{" "}
                {summaries.length} 次执行
              </p>
            </div>
          </div>
          <button
            aria-label="刷新扫描记录"
            onClick={() => setRefresh((n) => n + 1)}
            disabled={loading}
            className="tg-button inline-flex items-center gap-2"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            刷新记录
          </button>
        </header>
        <ScanWorkflow summary={visible[0]?.primary} />
        <p className="text-xs leading-6 text-slate-500">
          按日期展示当前市场已保存的历史，不受行情来源选择限制。每天优先展示可查看、扫描范围较大的批次；同日其他执行可展开，明细和图表仍沿用各自原始批次。
        </p>
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-600"
          >
            {error}
            <button
              onClick={() => setRefresh((n) => n + 1)}
              className="ml-3 underline"
            >
              重试
            </button>
          </div>
        )}
        <section aria-label="历史扫描" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-700">
              历史扫描{" "}
              <span className="ml-2 text-xs font-normal text-slate-500">
                按交易日从新到旧
              </span>
            </h2>
            {historyDates.length > 0 && (
              <select
                aria-label="筛选扫描记录日期"
                className="tg-input py-1.5"
                value={historyDate}
                onChange={(e) => setHistoryDate(e.target.value)}
              >
                <option value="">全部日期</option>
                {historyDates.map((day) => (
                  <option key={day}>{day}</option>
                ))}
              </select>
            )}
          </div>
          {loading ? (
            <p
              role="status"
              className="rounded-xl border border-slate-200 p-8 text-center text-sm text-slate-500"
            >
              正在读取扫描记录…
            </p>
          ) : summaries.length === 0 && !error ? (
            <div className="rounded-xl border border-dashed border-slate-200 p-6 sm:p-8">
              <p className="text-sm font-medium text-slate-700">
                当前暂无已保存的扫描记录
              </p>
              <p className="mt-2 text-sm text-slate-500">
                每日任务完成后，扫描结果会显示在这里。
              </p>
            </div>
          ) : (
            visible.map(({ primary: s, others }) => {
              const inProgress = ["queued", "running"].includes(s.status);
              const missing =
                (s.filterCounts?.missing_target_bar || 0) +
                (s.filterCounts?.insufficient_history || 0);
              const metrics: [string, number | undefined][] = [
                ["命中股票", s.hitStockCount],
                ["≥2 共振", s.candidateCount],
                ["涉及行业", s.hitIndustryCount],
                ["共振行业", s.resonanceIndustryCount],
              ];
              return (
                <article
                  key={s.scanDate}
                  className="overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:border-slate-300"
                >
                  <button
                    key={s.id}
                    onClick={() => onSelectDate(s.id, s.source, s.adjustment)}
                    className="group w-full p-4 text-left transition hover:bg-slate-50 sm:p-5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <time className="font-semibold tabular-nums text-slate-900">
                          {s.scanDate}
                        </time>
                        {s.executionDate && (
                          <span className="text-xs text-slate-500">
                            执行于{" "}
                            {new Date(s.executionDate).toLocaleString("zh-CN", {
                              timeZone: "Asia/Shanghai",
                              month: "2-digit",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        )}
                        <span
                          className={`rounded-md px-2 py-0.5 text-xs ${s.marketRegime === "bull" ? "bg-emerald-500/10 text-emerald-700" : s.marketRegime === "bear" ? "bg-red-500/10 text-red-600" : "bg-slate-200/60 text-slate-600"}`}
                        >
                          {REGIME[s.marketRegime] || "环境未知"}
                        </span>
                        {s.status !== "success" && (
                          <span className="text-xs text-amber-700">
                            {STATUS[s.status] || s.status}
                          </span>
                        )}
                        {s.recordOrigin === "legacy_scan_cache" && (
                          <span className="text-xs text-slate-500">
                            历史导入
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-slate-500">
                        {s.totalStockCount == null || s.filteredOutCount == null
                          ? `已扫描 ${count(s.scannedStockCount ?? s.tradableCount)} 只 · 原记录未保存初筛总量`
                          : `股票池 ${count(s.totalStockCount)} 只，过滤 ${count(s.filteredOutCount)} 只后扫描 ${count(s.scannedStockCount ?? s.tradableCount)} 只`}
                      </span>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {metrics.map(([label, value]) => (
                        <div key={label}>
                          <div
                            className={`text-xl font-semibold tabular-nums ${label === "命中股票" ? "text-emerald-700" : "text-slate-700"}`}
                          >
                            {inProgress ? "…" : count(value)}
                          </div>
                          <div className="mt-1 text-xs text-slate-500">
                            {label}
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3">
                      <div className="flex flex-wrap gap-2">
                        {s.topSectors.slice(0, 3).map((v) => (
                          <span
                            key={v.sector}
                            className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-500"
                          >
                            {v.sector}
                          </span>
                        ))}
                      </div>
                      <span className="inline-flex items-center gap-1 text-xs text-slate-500 group-hover:text-emerald-700">
                        查看当日明细
                        <ArrowRight className="h-3.5 w-3.5" />
                      </span>
                    </div>
                    {(s.error || missing > 0 || inProgress) && (
                      <p className="mt-3 text-xs text-amber-700/80">
                        {s.error ||
                          (inProgress
                            ? "任务执行中，刷新记录查看最新状态"
                            : `${count(missing)} 个标的缺当日行情或历史不足，详情保留具体原因`)}
                      </p>
                    )}
                    {s.dataWarnings?.map((warning) => (
                      <p
                        className="mt-2 text-xs leading-5 text-slate-500"
                        key={warning}
                      >
                        {warning}
                      </p>
                    ))}
                  </button>
                  {others.length > 0 && (
                    <details className="border-t border-slate-100 px-5 py-3">
                      <summary className="cursor-pointer text-xs text-slate-500">
                        同日其他执行（{others.length} 次）
                      </summary>
                      <div className="mt-3 space-y-2">
                        {others.map((other) => (
                          <button
                            className="flex w-full flex-wrap items-center justify-between gap-2 rounded-md bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 hover:bg-blue-50"
                            key={other.id}
                            onClick={() =>
                              onSelectDate(
                                other.id,
                                other.source,
                                other.adjustment,
                              )
                            }
                          >
                            <span>
                              {other.executionDate
                                ? new Date(other.executionDate).toLocaleString(
                                    "zh-CN",
                                    { timeZone: "Asia/Shanghai" },
                                  )
                                : "时间未记录"}{" "}
                              · {STATUS[other.status] || other.status} · 扫描{" "}
                              {count(
                                other.scannedStockCount ?? other.tradableCount,
                              )}{" "}
                              只 · 命中 {count(other.hitStockCount)} 只
                            </span>
                            <span className="text-blue-700">
                              查看这次执行 →
                            </span>
                          </button>
                        ))}
                      </div>
                    </details>
                  )}
                </article>
              );
            })
          )}
        </section>
      </div>
    </SelectionShell>
  );
}
