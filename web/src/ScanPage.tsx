import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, RefreshCw, ScanLine } from "lucide-react";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import {
  CachedScanDate,
  fetchScanDates,
  fetchScanSummaries,
  startScan,
} from "./api";
import { ScanSummary } from "./types";
import CalendarPicker from "./CalendarPicker";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { DAILY_STRATEGIES } from "./strategies";

interface Props extends SelectionNavProps {
  onBack: () => void;
  onSelectDate: (date: string) => void;
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
  typeof value === "number" ? value.toLocaleString() : "—";

export default function ScanPage({ onBack, onSelectDate, ...nav }: Props) {
  const { market, source, adjustment, info } = useMarket();
  const [runDate, setRunDate] = useState("");
  const [dates, setDates] = useState<CachedScanDate[]>([]);
  const [summaries, setSummaries] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [historyDate, setHistoryDate] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDateError(null);
    setSummaries([]);
    setDates([]);
    setRunDate("");
    setHistoryDate("");
    // History remains usable even when reading cache availability fails.
    Promise.allSettled([fetchScanSummaries(), fetchScanDates()]).then(
      ([history, cache]) => {
        if (cancelled) return;
        if (history.status === "fulfilled") {
          setSummaries(
            [...history.value].sort(
              (a, b) =>
                b.scanDate.localeCompare(a.scanDate) ||
                (b.executionDate || "").localeCompare(a.executionDate || ""),
            ),
          );
        } else
          setError(
            history.reason instanceof Error
              ? history.reason.message
              : "扫描记录读取失败",
          );
        if (cache.status === "fulfilled") {
          setDates(cache.value);
          setRunDate(cache.value[0]?.date || "");
        } else
          setDateError(
            cache.reason instanceof Error
              ? cache.reason.message
              : "可用交易日读取失败",
          );
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [market, source, adjustment, refresh]);

  useEffect(() => {
    if (!summaries.some((s) => s.status === "running" || s.status === "queued"))
      return;
    let cancelled = false;
    const timer = setTimeout(() => {
      fetchScanSummaries()
        .then((rows) => {
          if (!cancelled) setSummaries(rows);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    }, 3000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [summaries]);

  async function launchScan() {
    setStarting(true);
    setError(null);
    try {
      const result = await startScan(runDate);
      if (mounted.current) onSelectDate(result.run_id);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setStarting(false);
    }
  }
  const selectedCache = dates.find((d) => d.date === runDate);
  const currentSource = info?.sources.find(
    (s) => s.source === source && s.adjustment === adjustment,
  );
  const alternatives =
    info?.sources.filter(
      (s) =>
        (s.source !== source || s.adjustment !== adjustment) &&
        s.scan_count > 0,
    ) || [];
  const historyDates = [...new Set(summaries.map((s) => s.scanDate))];
  const visible = historyDate
    ? summaries.filter((s) => s.scanDate === historyDate)
    : summaries;

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
              <h1 className="text-xl font-semibold text-white">每日扫描</h1>
              <p className="mt-1 text-xs text-slate-400">
                {info?.label} · {source || "暂无行情来源"} ·{" "}
                {
                  (
                    {
                      forward: "前复权",
                      none: "不复权",
                      backward: "后复权",
                    } as Record<string, string>
                  )[adjustment]
                }{" "}
                · 缓存截止 {currentSource?.max_date || "未知"}
              </p>
            </div>
          </div>
          <button
            aria-label="刷新扫描记录"
            onClick={() => setRefresh((n) => n + 1)}
            disabled={loading || starting}
            className="tg-button inline-flex items-center gap-2"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            />
            刷新
          </button>
        </header>

        <section
          className="rounded-xl border border-slate-700 bg-slate-900/70 p-4 sm:p-5"
          aria-label="新建扫描"
        >
          <div className="mb-4 flex items-center gap-2">
            <ScanLine className="h-4 w-4 text-emerald-400" />
            <h2 className="text-sm font-semibold text-white">扫描已保存行情</h2>
          </div>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <CalendarPicker
              availableDates={dates.map((d) => d.date)}
              selectedDate={runDate}
              onSelectDate={setRunDate}
              disabled={loading || starting}
            />
            <button
              disabled={loading || starting || !source || !selectedCache}
              onClick={launchScan}
              className="tg-primary inline-flex items-center gap-2"
            >
              {starting ? "正在创建任务…" : "开始扫描"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-4 text-xs leading-5 text-slate-400">
            {loading
              ? "正在读取可用交易日…"
              : dateError
                ? dateError
                : selectedCache
                  ? `${runDate} 有 ${count(selectedCache.symbols)} 个标的缓存，扫描前仍会检查历史长度和过滤条件。`
                  : "当前市场、来源和复权尚无股票缓存，请先导入或同步行情。"}{" "}
            扫描使用同源缓存，不自动下载行情。
          </p>
        </section>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-300"
          >
            {error}
          </div>
        )}

        <section aria-label="历史扫描" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-200">
              扫描记录{" "}
              <span className="ml-2 font-normal text-slate-500">
                {historyDates.length} 个交易日 · {summaries.length} 次执行
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
              className="rounded-xl border border-slate-800 p-8 text-center text-sm text-slate-400"
            >
              正在读取扫描记录…
            </p>
          ) : summaries.length === 0 && !error ? (
            <div className="rounded-xl border border-dashed border-slate-700 p-6 sm:p-8">
              <p className="text-sm font-medium text-slate-200">
                {source || "当前来源"} 尚无扫描记录
              </p>
              <p className="mt-2 text-sm text-slate-400">
                {dates.length
                  ? "选择上方有缓存的交易日开始扫描，结果会保存在这里。"
                  : "导入或同步该来源行情后，即可选择交易日扫描。"}
              </p>
              {alternatives.length > 0 && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-500">
                    其他来源已有记录：
                  </span>
                  {alternatives.map((s) => (
                    <button
                      key={s.source + s.adjustment}
                      className="tg-button text-xs"
                      onClick={() =>
                        openPath(
                          scopedPath("/scan", {
                            source: s.source,
                            adjustment: s.adjustment,
                          }),
                        )
                      }
                    >
                      查看 {s.source} · {s.latest_scan_date} · {s.scan_count} 次
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            visible.map((s) => {
              const inProgress =
                s.status === "queued" || s.status === "running";
              const missing =
                (s.filterCounts?.missing_target_bar || 0) +
                (s.filterCounts?.insufficient_history || 0);
              return (
                <button
                  key={s.id}
                  onClick={() => onSelectDate(s.id)}
                  className="group w-full rounded-xl border border-slate-700/70 bg-slate-900/60 p-4 text-left transition hover:border-slate-500 hover:bg-slate-800/70"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <time className="font-semibold tabular-nums text-white">
                        {s.scanDate}
                      </time>
                      <span
                        className={`rounded-md px-2 py-0.5 text-xs ${s.status === "success" ? "bg-emerald-500/10 text-emerald-300" : s.status === "partial" ? "bg-amber-500/10 text-amber-300" : s.status === "failed" || s.status === "stale" ? "bg-red-500/10 text-red-300" : "bg-cyan-500/10 text-cyan-300"}`}
                      >
                        {STATUS[s.status] || s.status}
                      </span>
                      <span className="text-xs text-slate-500">
                        {REGIME[s.marketRegime] || "环境未知"}
                      </span>
                    </div>
                    <span className="inline-flex items-center gap-1 text-xs text-slate-400 group-hover:text-emerald-300">
                      查看明细
                      <ArrowRight className="h-3.5 w-3.5" />
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    {[
                      {
                        label: "参与扫描",
                        value: s.scannedStockCount ?? s.tradableCount,
                      },
                      {
                        label: "命中策略",
                        value: s.hitStockCount ?? s.candidateCount,
                      },
                      { label: "≥2 策略共振", value: s.candidateCount },
                    ].map((metric) => (
                      <div key={metric.label}>
                        <div
                          className={`text-lg font-semibold tabular-nums ${metric.label === "命中策略" ? "text-emerald-300" : "text-slate-200"}`}
                        >
                          {inProgress ? "…" : count(metric.value)}
                        </div>
                        <div className="mt-0.5 text-xs text-slate-500">
                          {metric.label}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500">
                    <span>
                      {s.error ||
                        (inProgress
                          ? "任务执行中，可查看进度"
                          : missing
                            ? `${count(missing)} 个标的缺当日行情或历史不足，查看明细了解原因`
                            : s.hitStockCount === 0
                              ? "本次未命中策略，可查看过滤原因"
                              : s.topSectors
                                  .slice(0, 3)
                                  .map((v) => v.sector)
                                  .join(" · ") || "未记录行业")}
                    </span>
                    <span>
                      {s.executionDate
                        ? new Date(s.executionDate).toLocaleString("zh-CN", {
                            timeZone: "Asia/Shanghai",
                          })
                        : ""}
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </section>

        <details className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 text-sm text-slate-400">
          <summary className="cursor-pointer text-xs text-slate-400">
            扫描规则与策略说明
          </summary>
          <div className="mt-4 grid gap-4 text-xs leading-6 sm:grid-cols-3">
            <div>
              <h3 className="font-medium text-slate-200">1. 市场环境</h3>
              <p>按同源基准的 MA20 和斜率判断；缺基准数据时保留未知。</p>
            </div>
            <div>
              <h3 className="font-medium text-slate-200">2. 股票池过滤</h3>
              <p>
                检查停牌、上市历史、流动性；A 股额外检查 ST
                与板块涨跌幅。每个过滤原因均保存。
              </p>
            </div>
            <div>
              <h3 className="font-medium text-slate-200">3. 五策略扫描</h3>
              <p>
                {DAILY_STRATEGIES.map((s) => s.title).join("、")}
                。命中数与共振数分别记录。
              </p>
            </div>
          </div>
        </details>
      </div>
    </SelectionShell>
  );
}
