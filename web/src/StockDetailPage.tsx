import { Suspense, lazy, useEffect, useState } from "react";
import {
  fetchKline,
  fetchStockProfile,
  fetchStockSignals,
  realPortfolio,
  StockSignal,
} from "./api";
import { KlineData, StockProfile } from "./types";
import { RealAccount } from "./realTypes";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { useMarket } from "./MarketContext";
import WatchButton from "./WatchButton";
import TradeCheck from "./TradeCheck";
import { createAlert } from "./workspaceApi";
import { STRATEGY_MAP } from "./strategies";

const Plot = lazy(() => import("react-plotly.js"));

interface Props extends SelectionNavProps {
  stockCode: string;
  stockName: string | null;
  onBack: () => void;
  onPortfolio: () => void;
}

interface ChartPrefs {
  days: number;
  ma: boolean;
  bollinger: boolean;
  signals: boolean;
}
const defaultPrefs: ChartPrefs = {
  days: 260,
  ma: true,
  bollinger: false,
  signals: true,
};
function readPrefs(): ChartPrefs {
  try {
    const p = JSON.parse(
      localStorage.getItem("tradeguard-chart-prefs-v1") || "{}",
    );
    return {
      days: [60, 120, 260, 520].includes(p.days) ? p.days : 260,
      ma: typeof p.ma === "boolean" ? p.ma : true,
      bollinger: p.bollinger === true,
      signals: typeof p.signals === "boolean" ? p.signals : true,
    };
  } catch {
    return defaultPrefs;
  }
}

function fmt(n: number | null | undefined) {
  return n == null
    ? "—"
    : n.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

export default function StockDetailPage({
  stockCode,
  stockName,
  onBack,
  onPortfolio,
  onHome,
  onScan,
  onScreener,
}: Props) {
  const { market, source, adjustment } = useMarket();
  const endDate =
    new URLSearchParams(location.search).get("endDate") || undefined;
  const [prefs, setPrefs] = useState<ChartPrefs>(readPrefs);
  const [alertMessage, setAlertMessage] = useState("");
  const [alertBusy, setAlertBusy] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem("tradeguard-chart-prefs-v1", JSON.stringify(prefs));
    } catch {
      /* preferences apply this visit */
    }
  }, [prefs]);
  const [bars, setBars] = useState<KlineData[]>([]);
  const [profile, setProfile] = useState<StockProfile | null>(null);
  const [signals, setSignals] = useState<StockSignal[]>([]);
  const [accounts, setAccounts] = useState<RealAccount[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setBars([]);
    setProfile(null);
    setSignals([]);
    Promise.all([
      fetchKline(stockCode, prefs.days, endDate),
      fetchStockProfile(stockCode, endDate),
      fetchStockSignals(stockCode, endDate),
    ])
      .then(([nextBars, nextProfile, nextSignals]) => {
        if (cancelled) return;
        setBars(nextBars);
        setProfile(nextProfile);
        setSignals(nextSignals);
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
  }, [stockCode, market, source, adjustment, endDate, prefs.days]);

  const [accountError, setAccountError] = useState("");
  const [accountsLoading, setAccountsLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setAccounts([]);
    setAccountError("");
    setAccountsLoading(true);
    realPortfolio()
      .then((portfolio) => {
        if (!cancelled) setAccounts(portfolio.accounts);
      })
      .catch(() => {
        if (!cancelled)
          setAccountError("账户记录读取失败，请刷新重试；不据此判断为空仓。");
      })
      .finally(() => {
        if (!cancelled) setAccountsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stockCode]);

  const matchingAccounts = accounts.filter((account) =>
    account.snapshot?.positions.some(
      (position) => position.symbol === stockCode,
    ),
  );
  const latest = bars[bars.length - 1];
  const currency = market === "CN" ? "CNY" : market === "US" ? "USD" : "HKD";
  const marked = signals
    .map((signal) => {
      const bar = bars.find((item) => item.date === signal.date);
      return bar ? { ...signal, high: bar.high } : null;
    })
    .filter((item): item is StockSignal & { high: number } => item !== null);

  return (
    <SelectionShell
      onHome={onHome || onBack}
      onScan={onScan}
      onScreener={onScreener}
      onPortfolio={onPortfolio}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            aria-label="返回"
            onClick={onBack}
            className="rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-slate-600"
          >
            ←
          </button>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              {profile?.name || stockName || stockCode}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {stockCode} · {profile?.industry || "行业未记录"} · {currency}
            </p>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold text-slate-900">
            {fmt(latest?.close)}{" "}
            <span className="text-sm text-slate-500">{currency}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            缓存收盘 · {latest?.date || "暂无行情"}
          </p>
        </div>
      </div>
      {error && (
        <p
          role="alert"
          className="rounded-xl border border-red-500/30 p-4 text-red-600"
        >
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-start gap-3">
        <WatchButton symbol={stockCode} />
        <form
          className="flex flex-wrap gap-2"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            setAlertBusy(true);
            setAlertMessage("");
            try {
              await createAlert(
                stockCode,
                String(f.get("condition")),
                String(f.get("target")),
              );
              setAlertMessage(
                "价格条件已保存，在提醒页评估缓存或通过本地命令评估",
              );
            } catch (err) {
              setAlertMessage((err as Error).message);
            } finally {
              setAlertBusy(false);
            }
          }}
        >
          <select
            name="condition"
            aria-label="价格提醒方向"
            className="tg-input"
          >
            <option value="above">收盘价高于或等于</option>
            <option value="below">收盘价低于或等于</option>
          </select>
          <input
            aria-label="价格提醒目标"
            name="target"
            required
            inputMode="decimal"
            placeholder={currency + " 目标价格"}
            className="tg-input w-36"
          />
          <button disabled={alertBusy} className="tg-button">
            创建提醒
          </button>
        </form>
      </div>
      {alertMessage && (
        <p role="status" className="text-sm text-cyan-700">
          {alertMessage}
        </p>
      )}
      {endDate && (
        <p className="text-xs text-amber-700">
          历史图表截止 {endDate}
          ；下方账户为最近保存的真实观察，各自时间单独标注。
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="tg-panel" aria-label="股票基础与行业信息">
          <h2 className="tg-title">股票基础与行业信息</h2>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">
            {[
              ["股票名称", profile?.name || stockName || stockCode],
              ["股票代码", stockCode],
              ["所属市场", { CN: "A 股", US: "美股", HK: "港股" }[market]],
              ["所属行业", profile?.industry || "未记录"],
              ["最近行情日期", profile?.lastDataDate || "暂无行情"],
              [
                "历史日线",
                profile?.dataDays == null ? "—" : `${profile.dataDays} 根`,
              ],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="mt-1 text-slate-700">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="tg-panel" aria-label="最新行情与扫描摘要">
          <h2 className="tg-title">
            {endDate ? "所选日期行情与扫描摘要" : "最新行情与扫描摘要"}
          </h2>
          <dl className="mt-4 grid grid-cols-3 gap-4 text-sm">
            {[
              ["收盘", fmt(latest?.close)],
              ["开盘", fmt(latest?.open)],
              ["最高", fmt(latest?.high)],
              ["最低", fmt(latest?.low)],
              ["成交量", fmt(latest?.volume)],
              ["币种", currency],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="mt-1 text-slate-700">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-xs leading-6 text-slate-500">
            {profile?.latestScan?.scanDate
              ? `${profile.latestScan.scanDate} · 共振 ${profile.latestScan.resonanceCount ?? "未知"} · ${profile.latestScan.strategiesHit.map((name) => STRATEGY_MAP[name]?.title || name).join("、")}`
              : "所选日期范围内暂无已保存的策略命中"}
          </p>
        </section>
      </div>
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white p-4">
        <div className="mb-4 flex justify-between">
          <h2 className="font-semibold text-slate-900">行情、均线与策略信号</h2>
          <span className="text-xs text-slate-500">
            {bars.length} 根日线 · {marked.length} 个信号
          </span>
        </div>
        <div className="mb-4 flex flex-wrap gap-4 text-xs text-slate-500">
          <label>
            图表范围{" "}
            <select
              aria-label="图表范围"
              value={prefs.days}
              onChange={(e) =>
                setPrefs((p) => ({ ...p, days: Number(e.target.value) }))
              }
              className="tg-input ml-2"
            >
              {[60, 120, 260, 520].map((d) => (
                <option key={d} value={d}>
                  {d} 根日线
                </option>
              ))}
            </select>
          </label>
          {(
            [
              ["ma", "均线"],
              ["bollinger", "布林带"],
              ["signals", "策略标记"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs[key]}
                onChange={(e) =>
                  setPrefs((p) => ({ ...p, [key]: e.target.checked }))
                }
              />
              {label}
            </label>
          ))}
          <span className="self-center">偏好在本浏览器保留</span>
        </div>
        {loading ? (
          <p className="p-10 text-center text-slate-500">正在加载真实行情…</p>
        ) : bars.length === 0 ? (
          <p className="p-10 text-center text-slate-500">
            所选日期范围内暂无该股票的已保存行情。
          </p>
        ) : (
          <Suspense fallback={<p className="text-slate-500">正在加载图表…</p>}>
            <Plot
              data={[
                {
                  type: "candlestick",
                  x: bars.map((bar) => bar.date),
                  open: bars.map((bar) => bar.open),
                  high: bars.map((bar) => bar.high),
                  low: bars.map((bar) => bar.low),
                  close: bars.map((bar) => bar.close),
                  name: "日 K",
                  increasing: { line: { color: "#ef4444" } },
                  decreasing: { line: { color: "#10b981" } },
                },
                ...(prefs.ma ? ([5, 10, 20, 60] as const) : []).map(
                  (period, index) => ({
                    type: "scatter" as const,
                    mode: "lines" as const,
                    x: bars.map((bar) => bar.date),
                    y: bars.map((bar) => bar[`ma${period}`] ?? null),
                    name: `MA${period}`,
                    line: {
                      width: 1,
                      color: ["#b45309", "#7c3aed", "#0284c7", "#f97316"][
                        index
                      ],
                    },
                  }),
                ),
                ...(prefs.bollinger
                  ? (["bb_upper", "bb_middle", "bb_lower"] as const).map(
                      (key) => ({
                        type: "scatter" as const,
                        mode: "lines" as const,
                        x: bars.map((b) => b.date),
                        y: bars.map((b) => b[key] ?? null),
                        name: key,
                        line: {
                          width: 1,
                          color: "#0284c7",
                          dash: "dot" as const,
                        },
                      }),
                    )
                  : []),
                {
                  visible: prefs.signals,
                  type: "scatter",
                  mode: "markers",
                  name: "策略信号",
                  x: marked.map((item) => item.date),
                  y: marked.map((item) => item.high * 1.01),
                  text: marked.map((item) =>
                    item.strategies
                      .map((name) => STRATEGY_MAP[name]?.title ?? name)
                      .join("、"),
                  ),
                  hovertemplate: "%{x}<br>%{text}<extra></extra>",
                  marker: { color: "#d97706", size: 11, symbol: "triangle-up" },
                },
              ]}
              layout={{
                height: 520,
                autosize: true,
                modebar: { bgcolor: "rgba(255,255,255,0.95)", color: "#64748b", activecolor: "#2563eb", orientation: "h" },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                font: { color: "#64748b" },
                margin: { l: 55, r: 20, t: 20, b: 40 },
                xaxis: {
                  rangeslider: { visible: false },
                  type: "category",
                  gridcolor: "#e2e8f0",
                  nticks: 10,
                },
                yaxis: { gridcolor: "#e2e8f0" },
                legend: { orientation: "h", y: 1.06 },
              }}
              config={{ responsive: true, displaylogo: false }}
              style={{ width: "100%" }}
              useResizeHandler
            />
          </Suspense>
        )}
      </section>
      <TradeCheck
        key={stockCode + market + source + adjustment}
        symbol={stockCode}
      />
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold text-slate-900">信号记录</h2>
        {marked.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">
            所选图表范围内暂无已保存的策略命中。
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {marked
              .slice()
              .reverse()
              .slice(0, 12)
              .map((item) => (
                <li
                  key={item.date}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700"
                >
                  <span className="text-amber-700">{item.date}</span>
                  <span className="mx-2 text-slate-500">
                    共振 {item.resonanceCount}
                  </span>
                  {item.strategies
                    .map((name) => STRATEGY_MAP[name]?.title ?? name)
                    .join("、")}
                  {item.reasons.length > 0 && (
                    <p className="mt-1 text-xs text-slate-500">
                      {item.reasons.join("；")}
                    </p>
                  )}
                </li>
              ))}
          </ul>
        )}
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5">
        <div className="mb-4 flex justify-between">
          <h2 className="font-semibold text-slate-900">该标的的真实持仓与条件单</h2>
          <button onClick={onPortfolio} className="text-sm text-cyan-700">
            查看全部账户 →
          </button>
        </div>
        {accountsLoading ? (
          <p className="text-sm text-slate-500">正在读取该标的的账户记录…</p>
        ) : accountError ? (
          <p role="alert" className="text-sm text-amber-700">
            {accountError}
          </p>
        ) : matchingAccounts.length === 0 ? (
          <p className="text-sm text-slate-500">
            已保存的真实账户中未记录该标的。这里不会创建模拟仓位。
          </p>
        ) : (
          matchingAccounts.map((account) => {
            const position = account.snapshot!.positions.find(
              (item) => item.symbol === stockCode,
            )!;
            const orders = account.snapshot!.orders.filter(
              (item) => item.symbol === stockCode,
            );
            return (
              <div
                key={account.id}
                className="mb-3 rounded-xl border border-slate-200 p-4"
              >
                <div className="flex flex-wrap justify-between gap-2 text-sm text-slate-700">
                  <b>{account.label}</b>
                  <span>
                    {position.quantity} 股 · 成本{" "}
                    {position.average_cost || "未记录"} {position.currency}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  观察时间：
                  {new Date(
                    position.observed_at || account.snapshot!.as_of,
                  ).toLocaleString("zh-CN")}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {orders.length ? (
                    orders.map((order, index) => (
                      <span
                        key={index}
                        className="rounded border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-600"
                      >
                        {order.order_kind === "take_profit"
                          ? "止盈"
                          : order.order_kind === "trailing"
                            ? "移动条件单"
                            : "止损 / 订单"}
                        ：
                        {order.trigger_price ||
                          order.limit_price ||
                          (order.trailing_percent
                            ? `${order.trailing_percent}%`
                            : "未记录")}{" "}
                        ·{" "}
                        {order.evidence === "broker_verified"
                          ? "券商快照"
                          : order.evidence === "manually_confirmed"
                            ? "人工确认"
                            : "待确认记录"}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-amber-700">
                      没有已保存的条件单，不能据此断言没有挂单。
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </section>
    </SelectionShell>
  );
}
