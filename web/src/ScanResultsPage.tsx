import WatchButton from "./WatchButton";
import ScanProgress from "./ScanProgress";
import { useMarket } from "./MarketContext";
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchKline,
  fetchScanResults,
  fetchScanSectors,
  fetchScanSummary,
} from "./api";
import { KlineData, ScanResult, ScanSector, ScanSummary } from "./types";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { STRATEGY_MAP } from "./strategies";

interface Props extends SelectionNavProps {
  scanDate: string;
  onBack: () => void;
  onSelectStock: (code: string, name: string | null, asOf?: string) => void;
}

type TabType = "list" | "sectors";

const Plot = lazy(() => import("react-plotly.js"));
const CHART_PRELOAD_MARGIN_PX = 120;
const MAX_PARALLEL_CHART_REQUESTS = 2;

type PendingChartRequest = {
  id: number;
  run: () => Promise<void>;
};

let nextChartRequestId = 0;
let activeChartRequestCount = 0;
let pendingChartRequests: PendingChartRequest[] = [];

function flushChartRequestQueue() {
  while (
    activeChartRequestCount < MAX_PARALLEL_CHART_REQUESTS &&
    pendingChartRequests.length > 0
  ) {
    const request = pendingChartRequests.shift();
    if (!request) {
      return;
    }

    activeChartRequestCount += 1;
    request.run().finally(() => {
      activeChartRequestCount = Math.max(0, activeChartRequestCount - 1);
      flushChartRequestQueue();
    });
  }
}

function enqueueChartRequest(run: () => Promise<void>) {
  const request: PendingChartRequest = {
    id: ++nextChartRequestId,
    run,
  };

  pendingChartRequests.push(request);
  flushChartRequestQueue();

  return () => {
    pendingChartRequests = pendingChartRequests.filter(
      (item) => item.id !== request.id,
    );
  };
}

const STRATEGY_LABELS: Record<string, string> = {
  ma_golden_cross: "均线金叉多头排列",
  macd_golden_cross: "MACD 金叉趋势",
  rsi_rebound: "RSI 超卖反弹",
  bollinger_breakout: "布林带放量突破",
  box_breakout: "箱体突破",
};

const REGIME_LABEL: Record<string, { text: string; color: string }> = {
  bull: {
    text: "牛市",
    color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
  },
  neutral: {
    text: "震荡",
    color: "text-yellow-400  bg-yellow-400/10  border-yellow-400/30",
  },
  unknown: {
    text: "未判断",
    color: "text-slate-400 bg-slate-700 border-slate-600",
  },
  bear: {
    text: "熊市",
    color: "text-red-400     bg-red-400/10     border-red-400/30",
  },
};

const REGIME_TOOLTIP: Record<string, string> = {
  bull: "计算规则：指数收盘价高于 MA20，且 MA20 近 5 日斜率为正。",
  neutral: "计算规则：指数未同时满足牛市或熊市条件，因此判定为震荡环境。",
  bear: "计算规则：指数收盘价低于 MA20，且 MA20 近 5 日斜率为负。",
};

const DEFAULT_SCAN_STRATEGIES = [
  "ma_golden_cross",
  "macd_golden_cross",
  "rsi_rebound",
  "bollinger_breakout",
  "box_breakout",
];

function formatCount(value: number | null | undefined) {
  return typeof value === "number" ? value.toLocaleString() : "--";
}

function formatMoneyInYi(value: number | null | undefined) {
  if (typeof value !== "number") {
    return "--";
  }
  return `${(value / 100000000).toFixed(value >= 100000000 ? 1 : 2)} 亿`;
}

function computeChartDays(scanDate: string) {
  const oneDay = 1000 * 60 * 60 * 24;
  const diff = Math.max(
    0,
    Math.ceil((Date.now() - new Date(scanDate).getTime()) / oneDay),
  );
  return Math.min(Math.max(diff + 120, 160), 500);
}

function LazyLatestChart({
  stockCode,
  scanDate,
  source,
}: {
  stockCode: string;
  scanDate: string;
  source?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [shouldLoad, setShouldLoad] = useState(false);
  const [chartData, setChartData] = useState<KlineData[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const chartDays = useMemo(() => computeChartDays(scanDate), [scanDate]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || shouldLoad) return;

    const rect = element.getBoundingClientRect();
    if (
      rect.top < window.innerHeight + CHART_PRELOAD_MARGIN_PX &&
      rect.bottom > -CHART_PRELOAD_MARGIN_PX
    ) {
      setShouldLoad(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setShouldLoad(true);
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: `${CHART_PRELOAD_MARGIN_PX}px 0px`, threshold: 0.15 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [shouldLoad]);

  useEffect(() => {
    if (!shouldLoad || chartData || loading) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const cancelQueuedRequest = enqueueChartRequest(async () => {
      try {
        const data = await fetchKline(stockCode, chartDays, scanDate, source);
        if (!cancelled) {
          setChartData(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "图表加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    });

    return () => {
      cancelled = true;
      cancelQueuedRequest();
    };
  }, [shouldLoad, chartData, stockCode, chartDays, scanDate, source]);

  const scanDayExists =
    chartData?.some((item) => item.date === scanDate) ?? false;

  return (
    <div
      ref={containerRef}
      className="mt-4 rounded-xl border border-slate-700 bg-slate-900/50 p-3 sm:p-4"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
            扫描时点行情
          </div>
          <div className="mt-1 text-sm text-slate-300">
            与本批次同源，行情截止 {scanDate}
          </div>
        </div>
        <div className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200">
          历史视图
        </div>
      </div>

      {!shouldLoad || loading ? (
        <div className="flex h-[360px] items-center justify-center rounded-lg border border-dashed border-slate-700 bg-slate-950/40 text-sm text-slate-500">
          {!shouldLoad ? "等待进入视区，准备加载图表..." : "图表加载中..."}
        </div>
      ) : error ? (
        <div className="flex h-[360px] items-center justify-center rounded-lg border border-red-700/50 bg-red-900/20 px-4 text-sm text-red-300">
          {error}
        </div>
      ) : !chartData || chartData.length === 0 ? (
        <div className="flex h-[360px] items-center justify-center rounded-lg border border-slate-700 bg-slate-950/40 text-sm text-slate-500">
          暂无图表数据
        </div>
      ) : (
        <>
          {!scanDayExists && (
            <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              当前最新图表窗口内未覆盖扫描日 {scanDate}，已尽量扩展最近区间。
            </div>
          )}
          <Suspense
            fallback={
              <div className="flex h-[360px] items-center justify-center rounded-lg border border-dashed border-slate-700 bg-slate-950/40 text-sm text-slate-500">
                图表组件加载中...
              </div>
            }
          >
            <Plot
              data={[
                {
                  type: "candlestick",
                  x: chartData.map((item) => item.date),
                  open: chartData.map((item) => item.open),
                  high: chartData.map((item) => item.high),
                  low: chartData.map((item) => item.low),
                  close: chartData.map((item) => item.close),
                  name: "K线",
                  increasing: { line: { color: "#ef4444" } },
                  decreasing: { line: { color: "#10b981" } },
                  xaxis: "x",
                  yaxis: "y",
                },
                {
                  type: "scatter",
                  x: chartData.map((item) => item.date),
                  y: chartData.map((item) => item.ma5 ?? null),
                  mode: "lines",
                  name: "MA5",
                  line: { color: "#38bdf8", width: 1.5 },
                  xaxis: "x",
                  yaxis: "y",
                },
                {
                  type: "scatter",
                  x: chartData.map((item) => item.date),
                  y: chartData.map((item) => item.ma10 ?? null),
                  mode: "lines",
                  name: "MA10",
                  line: { color: "#22c55e", width: 1.5 },
                  xaxis: "x",
                  yaxis: "y",
                },
                {
                  type: "scatter",
                  x: chartData.map((item) => item.date),
                  y: chartData.map((item) => item.ma20 ?? null),
                  mode: "lines",
                  name: "MA20",
                  line: { color: "#f59e0b", width: 1.5 },
                  xaxis: "x",
                  yaxis: "y",
                },
                {
                  type: "scatter",
                  x: chartData.map((item) => item.date),
                  y: chartData.map((item) => item.ma60 ?? null),
                  mode: "lines",
                  name: "MA60",
                  line: { color: "#a78bfa", width: 1.5 },
                  xaxis: "x",
                  yaxis: "y",
                },
                {
                  type: "bar",
                  x: chartData.map((item) => item.date),
                  y: chartData.map((item) => item.volume),
                  name: "成交量",
                  marker: { color: "#475569", opacity: 0.85 },
                  xaxis: "x",
                  yaxis: "y2",
                },
              ]}
              layout={{
                autosize: true,
                height: 430,
                margin: { l: 44, r: 20, t: 24, b: 36 },
                paper_bgcolor: "rgba(15, 23, 42, 0)",
                plot_bgcolor: "rgba(15, 23, 42, 0.55)",
                font: { size: 11, color: "#cbd5e1" },
                legend: {
                  orientation: "h",
                  y: 1.08,
                  x: 0,
                  bgcolor: "rgba(15, 23, 42, 0.35)",
                  bordercolor: "rgba(71, 85, 105, 0.45)",
                  borderwidth: 1,
                },
                hovermode: "x unified",
                hoverlabel: {
                  bgcolor: "#1e293b",
                  bordercolor: "#475569",
                  font: { color: "#f1f5f9", size: 11 },
                },
                xaxis: {
                  type: "category",
                  rangeslider: { visible: false },
                  showgrid: true,
                  gridcolor: "rgba(148, 163, 184, 0.16)",
                  zerolinecolor: "rgba(148, 163, 184, 0.18)",
                  tickangle: -35,
                },
                yaxis: {
                  title: { text: "价格" },
                  domain: [0.3, 1],
                  showgrid: true,
                  gridcolor: "rgba(148, 163, 184, 0.16)",
                  zerolinecolor: "rgba(148, 163, 184, 0.18)",
                },
                yaxis2: {
                  title: { text: "成交量" },
                  domain: [0, 0.22],
                  showgrid: false,
                },
                shapes: scanDayExists
                  ? [
                      {
                        type: "line",
                        x0: scanDate,
                        x1: scanDate,
                        yref: "paper",
                        y0: 0,
                        y1: 1,
                        line: { color: "#ef4444", width: 2, dash: "dashdot" },
                      },
                    ]
                  : [],
                annotations: scanDayExists
                  ? [
                      {
                        x: scanDate,
                        xanchor: "left",
                        yref: "paper",
                        y: 0.98,
                        yanchor: "top",
                        text: `扫描日 ${scanDate}`,
                        showarrow: false,
                        font: { size: 10, color: "#ef4444" },
                        bgcolor: "rgba(15, 23, 42, 0.92)",
                        bordercolor: "#ef4444",
                        borderwidth: 1,
                        borderpad: 4,
                      },
                    ]
                  : [],
              }}
              config={{
                responsive: true,
                displaylogo: false,
                modeBarButtonsToRemove: ["lasso2d", "select2d"],
              }}
              style={{ width: "100%" }}
              useResizeHandler={true}
            />
          </Suspense>
        </>
      )}
    </div>
  );
}

export default function ScanResultsPage({
  scanDate,
  onBack,
  onSelectStock,
  onHome,
  onScan,
  onScreener,
  onPortfolio,
  onMonitor,
}: Props) {
  const { market, source, adjustment } = useMarket();
  const [refreshTick, setRefreshTick] = useState(0);
  const [tab, setTab] = useState<TabType>("list");
  const [results, setResults] = useState<ScanResult[]>([]);
  const [sectors, setSectors] = useState<ScanSector[]>([]);
  const [summary, setSummary] = useState<
    (ScanSummary & { found: boolean }) | null
  >(null);
  const [minResonance, setMinResonance] = useState(1);
  const [showCharts, setShowCharts] = useState(false);
  const [showConditions, setShowConditions] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<
    "resonance" | "sector" | "code" | "name"
  >("resonance");
  const [industryFilter, setIndustryFilter] = useState("");
  const [strategyFilter, setStrategyFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResults([]);
    setSectors([]);
    setSummary(null);
    Promise.all([
      fetchScanResults(scanDate, minResonance),
      fetchScanSectors(scanDate),
      fetchScanSummary(scanDate),
    ])
      .then(([scanResults, scanSectors, scanSummary]) => {
        if (cancelled) return;
        setResults(scanResults);
        setSectors(attachSectorStocks(scanSectors, scanResults));
        setSummary(scanSummary);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scanDate, minResonance, refreshTick, market, source, adjustment]);

  function parseStrategies(raw: string[] | string): string[] {
    if (Array.isArray(raw)) return raw;
    try {
      return JSON.parse(raw);
    } catch {
      return [];
    }
  }

  function attachSectorStocks(
    items: ScanSector[],
    scanResults: ScanResult[],
  ): ScanSector[] {
    const stocksByIndustry = new Map<string, ScanResult[]>();
    for (const result of scanResults) {
      if (!result.industry) continue;
      const group = stocksByIndustry.get(result.industry) ?? [];
      group.push(result);
      stocksByIndustry.set(result.industry, group);
    }

    const normalized = items.map((item) => ({
      ...item,
      stocks: [...(stocksByIndustry.get(item.industry) ?? [])].sort(
        (left, right) => right.resonanceCount - left.resonanceCount,
      ),
    }));

    if (normalized.length > 0) {
      return normalized;
    }

    return Array.from(stocksByIndustry.entries())
      .map(([industry, stocks]) => ({
        industry,
        candidateCount: stocks.length,
        rsScore: stocks.some((stock) => stock.sectorStrength != null)
          ? stocks
              .filter((stock) => stock.sectorStrength != null)
              .reduce((sum, stock) => sum + stock.sectorStrength!, 0) /
            stocks.filter((stock) => stock.sectorStrength != null).length
          : null,
        stocks: [...stocks].sort(
          (left, right) => right.resonanceCount - left.resonanceCount,
        ),
      }))
      .sort((left, right) => (right.rsScore ?? 0) - (left.rsScore ?? 0));
  }

  const industries = useMemo(
    () =>
      Array.from(
        new Set(
          results
            .map((item) => item.industry)
            .filter((item): item is string => Boolean(item)),
        ),
      ).sort(),
    [results],
  );
  const visible = useMemo(() => {
    const filtered = results.filter((item) => {
      const strategies = parseStrategies(item.strategiesHit);
      if (industryFilter && item.industry !== industryFilter) return false;
      if (strategyFilter && !strategies.includes(strategyFilter)) return false;
      return true;
    });
    const value = (item: ScanResult) => {
      if (sortKey === "sector") return item.sectorStrength ?? -999;
      if (sortKey === "code") return item.stockCode;
      if (sortKey === "name") return item.stockName || item.stockCode;
      return item.resonanceCount;
    };
    return [...filtered].sort((left, right) => {
      const a = value(left);
      const b = value(right);
      if (typeof a === "number" && typeof b === "number") return b - a;
      return String(a).localeCompare(String(b), "zh-CN");
    });
  }, [results, industryFilter, strategyFilter, sortKey]);

  const displayDate = summary?.scanDate || scanDate;
  const totalStockCount =
    summary?.totalStockCount ?? summary?.tradableCount ?? 0;
  const filteredOutCount =
    summary?.filteredOutCount ??
    Math.max(totalStockCount - (summary?.tradableCount ?? 0), 0);
  const scannedStockCount =
    summary?.scannedStockCount ?? summary?.tradableCount ?? 0;
  const hitStockCount = summary?.hitStockCount ?? summary?.candidateCount ?? 0;
  const hitIndustryCount = summary?.hitIndustryCount ?? 0;
  const resonanceIndustryCount =
    summary?.resonanceIndustryCount ?? summary?.sectorCount ?? 0;
  const keptRatio =
    totalStockCount > 0 ? (scannedStockCount / totalStockCount) * 100 : null;
  const strategyNames =
    summary?.scanStrategies && summary.scanStrategies.length > 0
      ? summary.scanStrategies
      : DEFAULT_SCAN_STRATEGIES;
  const filterConfig = summary?.filterConfig ?? {};
  const summaryMetrics = [
    {
      label: "全市场股票",
      value: formatCount(totalStockCount),
      tone: "text-slate-100",
    },
    {
      label: "过滤后继续扫描",
      value: formatCount(scannedStockCount),
      tone: "text-cyan-300",
    },
    {
      label: "被过滤股票",
      value: formatCount(filteredOutCount),
      tone: "text-slate-300",
    },
    {
      label: "命中任一策略",
      value: formatCount(hitStockCount),
      tone: "text-emerald-400",
    },
    {
      label: "≥2 策略共振",
      value: formatCount(summary?.candidateCount),
      tone: "text-emerald-300",
    },
    {
      label: "涉及行业",
      value: formatCount(hitIndustryCount),
      tone: "text-amber-300",
    },
    {
      label: "共振行业",
      value: formatCount(resonanceIndustryCount),
      tone: "text-blue-400",
    },
    {
      label: "强势行业",
      value: formatCount(summary?.sectorCount),
      tone: "text-violet-300",
    },
  ];

  return (
    <SelectionShell
      currentSection="scan"
      onHome={onHome}
      onScan={onScan}
      onScreener={onScreener}
      onPortfolio={onPortfolio}
      onMonitor={onMonitor}
    >
      <div className="space-y-4">
        <ScanProgress
          runId={scanDate}
          onTerminal={() => setRefreshTick((t) => t + 1)}
        />
        {!!summary?.error && (
          <div className="rounded-lg border border-red-600 bg-red-950/30 p-3 text-red-300">
            {summary.error}
          </div>
        )}
        {!!summary?.warnings && Object.keys(summary.warnings).length > 0 && (
          <div className="rounded-lg border border-amber-600/30 bg-amber-950/20 p-3 text-sm text-amber-200">
            数据提示：
            {Object.entries(summary.warnings)
              .map(
                ([key, count]) =>
                  `${key === "listing_date_unverified" ? "上市日期尚未核验" : key} ${count} 个`,
              )
              .join("；")}
            。这些缺口未被补造。
          </div>
        )}
        {/* Header */}
        <div className="flex items-start gap-3">
          <button
            onClick={onBack}
            className="p-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 transition-all"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </button>
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-white sm:text-2xl">
              {displayDate} 扫描结果
            </h1>
            <p className="text-slate-400 text-sm">
              当日命中 {formatCount(hitStockCount)} 只，当前过滤条件下显示{" "}
              {formatCount(results.length)} 只
            </p>
          </div>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Scan Conditions Panel */}
        {summary?.found && (
          <div className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
            <button
              onClick={() => setShowConditions((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-750 transition-colors"
            >
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2 pr-3">
                <span className="text-slate-300 text-sm font-medium">
                  扫描条件
                </span>
                {(() => {
                  const regime = REGIME_LABEL[summary.marketRegime] ?? {
                    text: summary.marketRegime,
                    color: "text-slate-400 bg-slate-700 border-slate-600",
                  };
                  return (
                    <span
                      title={
                        REGIME_TOOLTIP[summary.marketRegime] ??
                        "市场环境按指数相对 MA20 与均线斜率判断。"
                      }
                      className={`cursor-help text-xs font-medium px-2 py-0.5 rounded border ${regime.color}`}
                    >
                      {regime.text}
                    </span>
                  );
                })()}
                <span className="text-slate-500 text-xs">
                  全市场 {formatCount(totalStockCount)} 只 → 过滤后{" "}
                  {formatCount(scannedStockCount)} 只 → 命中{" "}
                  {formatCount(hitStockCount)} 只 → ≥2 共振{" "}
                  {formatCount(summary.candidateCount)} 只
                </span>
              </div>
              <svg
                className={`w-4 h-4 text-slate-500 transition-transform ${showConditions ? "rotate-180" : ""}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </button>
            {showConditions && (
              <div className="border-t border-slate-700 px-4 py-4 space-y-4">
                <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
                  {summaryMetrics.map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-3"
                    >
                      <div className={`text-lg font-semibold ${metric.tone}`}>
                        {metric.value}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {metric.label}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
                  <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      筛选条件
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        过滤 ST：{filterConfig.filterSt === false ? "否" : "是"}
                      </div>
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        过滤新股：
                        {filterConfig.filterNewStock === false
                          ? "否"
                          : `上市满 ${formatCount(filterConfig.minListedDays ?? 365)} 天`}
                      </div>
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        流动性门槛：
                        {filterConfig.filterLiquidity === false
                          ? "未启用"
                          : `${formatMoneyInYi(filterConfig.minAvgVolume5d ?? 100000000)} / 近 5 日日均成交额`}
                      </div>
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        过滤停牌：
                        {filterConfig.filterSuspended === false ? "否" : "是"}
                      </div>
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        过滤涨跌停：
                        {filterConfig.filterLimit === false
                          ? "否"
                          : `是（阈值 ${(Number(filterConfig.limitPct ?? 0.095) * 100).toFixed(1)}%）`}
                      </div>
                      <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                        市值过滤：
                        {filterConfig.filterMarketCap
                          ? `${formatMoneyInYi(filterConfig.minMarketCap ?? 5000000000)} 起`
                          : "未启用"}
                      </div>
                      {summary.executionTime != null && (
                        <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                          执行耗时：{summary.executionTime.toFixed(1)} 秒
                        </div>
                      )}
                      {keptRatio != null && (
                        <div className="rounded-lg border border-slate-700 bg-slate-950/40 px-3 py-2">
                          保留比例：{keptRatio.toFixed(1)}%
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      扫描策略
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {strategyNames.map((strategyName) => {
                        const strategy = STRATEGY_MAP[strategyName];
                        const strategyTitle =
                          strategy?.title ??
                          STRATEGY_LABELS[strategyName] ??
                          strategyName;
                        const strategyDescription =
                          strategy?.description ??
                          "该策略命中后会计入当日扫描结果。";
                        const hitCount =
                          summary.strategyHitCounts?.[strategyName];
                        return (
                          <span
                            key={strategyName}
                            title={strategyDescription}
                            className="cursor-help rounded-full border border-emerald-700/40 bg-emerald-900/30 px-3 py-1.5 text-xs text-emerald-200"
                          >
                            {strategyTitle}
                            {typeof hitCount === "number" && (
                              <span className="ml-1 text-emerald-400">
                                {hitCount}
                              </span>
                            )}
                          </span>
                        );
                      })}
                    </div>

                    <div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      重点行业
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {summary.topSectors.length > 0 ? (
                        summary.topSectors.slice(0, 5).map((sector) => (
                          <span
                            key={sector.sector}
                            className="rounded-full border border-blue-700/40 bg-blue-900/20 px-3 py-1.5 text-xs text-blue-200"
                          >
                            {sector.sector}
                            <span className="ml-1 text-blue-400">
                              {sector.count}
                            </span>
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-500">
                          暂无重点行业数据
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Tabs */}
          <div className="flex bg-slate-800 border border-slate-700 rounded-lg p-1 gap-1">
            {(["list", "sectors"] as TabType[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-all ${
                  tab === t
                    ? "bg-emerald-600 text-white"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {t === "list" ? "候选股" : "行业共振"}
              </button>
            ))}
          </div>

          {/* Resonance filter */}
          {tab === "list" && (
            <div className="flex items-center gap-2">
              <span className="text-slate-400 text-sm">命中策略过滤:</span>
              {[1, 2, 3, 4].map((n) => (
                <button
                  key={n}
                  onClick={() => setMinResonance(n)}
                  className={`w-8 h-8 rounded text-sm font-bold transition-all ${
                    minResonance === n
                      ? "bg-emerald-600 text-white"
                      : "bg-slate-700 text-slate-300 hover:bg-slate-600"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          )}

          {tab === "list" && (
            <>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                排序
                <select
                  aria-label="排序"
                  value={sortKey}
                  onChange={(event) =>
                    setSortKey(event.target.value as typeof sortKey)
                  }
                  className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-white"
                >
                  <option value="resonance">共振数</option>
                  <option value="sector">行业强度</option>
                  <option value="code">代码</option>
                  <option value="name">名称</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                行业
                <select
                  aria-label="行业过滤"
                  value={industryFilter}
                  onChange={(event) => setIndustryFilter(event.target.value)}
                  className="max-w-[10rem] rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-white"
                >
                  <option value="">全部</option>
                  {industries.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                策略
                <select
                  aria-label="策略过滤"
                  value={strategyFilter}
                  onChange={(event) => setStrategyFilter(event.target.value)}
                  className="max-w-[12rem] rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-white"
                >
                  <option value="">全部</option>
                  {strategyNames.map((name) => (
                    <option key={name} value={name}>
                      {STRATEGY_LABELS[name] ?? name}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}

          {tab === "list" && (
            <label className="ml-auto flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={showCharts}
                onChange={(event) => setShowCharts(event.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500"
              />
              展示历史图表
            </label>
          )}
        </div>

        {loading ? (
          <div className="text-center text-slate-400 py-12">加载中...</div>
        ) : tab === "list" ? (
          /* Stock list */
          <div className="space-y-2">
            {visible.length === 0 && (
              <div className="text-center text-slate-500 py-12">
                无符合条件的候选股
              </div>
            )}
            {visible.map((r) => {
              const strats = parseStrategies(r.strategiesHit);
              return (
                <div
                  key={r.id}
                  className="bg-slate-800 border border-slate-700 rounded-lg p-4 hover:border-slate-500 cursor-pointer transition-all"
                  onClick={() =>
                    onSelectStock(r.stockCode, r.stockName, displayDate)
                  }
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="truncate text-white font-semibold">
                          {r.stockName || r.stockCode}
                        </span>
                        <span className="shrink-0 text-slate-400 text-sm">
                          {r.stockCode}
                        </span>
                        {r.industry && (
                          <span className="truncate text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded">
                            {r.industry}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-2">
                        {strats.map((s) => (
                          <span
                            key={s}
                            title={
                              STRATEGY_MAP[s]?.description ??
                              "该策略命中后会计入当日扫描结果。"
                            }
                            className="cursor-help text-xs bg-emerald-900/40 border border-emerald-700/50 text-emerald-300 px-2 py-0.5 rounded"
                          >
                            {STRATEGY_LABELS[s] ?? s}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-end justify-between sm:block sm:text-right">
                      <div className="text-emerald-400 font-bold text-lg">
                        {r.resonanceCount}
                      </div>
                      <div className="text-slate-500 text-xs">策略共振</div>
                      {r.sectorStrength != null && (
                        <div className="text-blue-400 text-xs mt-1">
                          RS {r.sectorStrength.toFixed(2)}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mt-3" onClick={(e) => e.stopPropagation()}>
                    <WatchButton symbol={r.stockCode} runId={summary?.id} />
                  </div>
                  {showCharts && (
                    <LazyLatestChart
                      stockCode={r.stockCode}
                      scanDate={displayDate}
                      source={summary?.source}
                    />
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          /* Sectors */
          <div className="space-y-3">
            {sectors.length === 0 && (
              <div className="text-center text-slate-500 py-12">
                暂无行业共振数据
              </div>
            )}
            {sectors.map((sec) => (
              <div
                key={sec.industry}
                className="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden"
              >
                <div className="px-4 py-3 bg-slate-750 border-b border-slate-700 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-white font-semibold">
                      {sec.industry}
                    </span>
                    <span className="text-sm text-slate-400">
                      {sec.candidateCount} 只
                    </span>
                  </div>
                  <span className="text-blue-400 font-bold">
                    RS {sec.rsScore == null ? "未计算" : sec.rsScore.toFixed(2)}
                  </span>
                </div>
                <div className="p-3 flex flex-wrap gap-2">
                  {sec.stocks.map((s) => (
                    <button
                      key={s.stockCode}
                      onClick={() =>
                        onSelectStock(s.stockCode, s.stockName, displayDate)
                      }
                      className="text-sm bg-slate-700 hover:bg-slate-600 border border-slate-600 rounded px-2 py-1 text-slate-200 transition-all"
                    >
                      {s.stockName ?? s.stockCode}
                      <span className="ml-1 text-emerald-400">
                        ×{s.resonanceCount}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </SelectionShell>
  );
}
