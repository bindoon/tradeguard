import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
  ReactNode,
} from "react";
import { RefreshCw } from "lucide-react";
import { marketInfoCache } from "./marketInfoCache";
export type Market = "CN" | "US" | "HK";
export interface SourceInfo {
  source: string;
  adjustment: string;
  rows: number;
  symbols: number;
  min_date: string;
  max_date: string;
  scan_count: number;
  latest_scan_date: string | null;
}
export interface MarketInfo {
  market: Market;
  label: string;
  currency: string;
  security_count: number;
  sources: SourceInfo[];
  default_source: string;
  default_adjustment: string;
  max_date: string | null;
  filter_defaults: Record<string, number | boolean>;
}
interface Context {
  market: Market;
  source: string;
  adjustment: string;
  info: MarketInfo | null;
  setMarket: (market: Market) => void;
  setSource: (source: string, adjustment?: string) => void;
  error: string | null;
  refreshing: boolean;
  refreshMarket: () => void;
}
const Store = createContext<Context | null>(null);
export function activeMarket(): Market {
  const value = sessionStorage.getItem("tradeguard-market");
  return value === "US" || value === "HK" ? value : "CN";
}
export function activeSource() {
  return sessionStorage.getItem("tradeguard-source-" + activeMarket()) || "";
}
export function activeAdjustment() {
  return (
    sessionStorage.getItem("tradeguard-adjustment-" + activeMarket()) ||
    "forward"
  );
}
export function scopedPath(
  path: string,
  overrides: Record<string, string> = {},
) {
  const url = new URL(path, location.origin);
  const scope = {
    market: activeMarket(),
    source: activeSource(),
    adjustment: activeAdjustment(),
    ...overrides,
  };
  Object.entries(scope).forEach(([key, value]) => {
    if (value) url.searchParams.set(key, value);
  });
  return url.pathname + url.search;
}
export function openPath(path: string) {
  history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
type Selection = {
  market: Market;
  source: string;
  adjustment: string;
  info: MarketInfo | null;
};

function requestedMarket(): Market {
  const params = new URLSearchParams(location.search);
  const ticker = decodeURIComponent(location.pathname.split("/").pop() || "");
  const requested =
    params.get("market") ||
    (location.pathname.startsWith("/stock/")
      ? ticker.endsWith(".US")
        ? "US"
        : ticker.endsWith(".HK")
          ? "HK"
          : "CN"
      : activeMarket());
  return requested === "US" || requested === "HK" ? requested : "CN";
}

function selectMarket(
  market: Market,
  info = marketInfoCache.peek(market),
): Selection {
  const params = new URLSearchParams(location.search);
  const explicit = requestedMarket() === market && params.get("source");
  const saved = sessionStorage.getItem("tradeguard-source-" + market) || "";
  const adjustment =
    sessionStorage.getItem("tradeguard-adjustment-" + market) || "forward";
  const chosen =
    info?.sources.find(
      (s) => s.source === saved && s.adjustment === adjustment,
    ) ||
    info?.sources.find(
      (s) =>
        s.source === info.default_source &&
        s.adjustment === info.default_adjustment,
    ) ||
    info?.sources[0];
  const source = explicit || (info ? chosen?.source || "" : saved);
  const adj = explicit
    ? params.get("adjustment") || "forward"
    : info
      ? chosen?.adjustment || "forward"
      : adjustment;
  sessionStorage.setItem("tradeguard-market", market);
  sessionStorage.setItem("tradeguard-source-" + market, source);
  sessionStorage.setItem("tradeguard-adjustment-" + market, adj);
  return { market, source, adjustment: adj, info };
}

export function MarketProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState(() =>
    selectMarket(requestedMarket()),
  );
  const { market, source, adjustment, info } = selection;
  const [failure, setFailure] = useState<{
    market: Market;
    message: string;
  } | null>(null);
  const error = failure?.market === market ? failure.message : null;
  const [refreshing, setRefreshing] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const forceNext = useRef(false);
  function setMarket(next: Market) {
    if (next === market) return;
    setFailure(null);
    setSelection(selectMarket(next));
  }
  function setSource(next: string, adj = "forward") {
    sessionStorage.setItem("tradeguard-source-" + market, next);
    sessionStorage.setItem("tradeguard-adjustment-" + market, adj);
    setSelection((current) => ({ ...current, source: next, adjustment: adj }));
  }
  function refreshMarket() {
    forceNext.current = true;
    setRefreshTick((n) => n + 1);
  }
  useEffect(() => {
    const readUrl = () => {
      const next = requestedMarket();
      setSelection((current) =>
        selectMarket(
          next,
          current.market === next ? current.info : marketInfoCache.peek(next),
        ),
      );
    };
    window.addEventListener("popstate", readUrl);
    return () => window.removeEventListener("popstate", readUrl);
  }, []);
  useEffect(() => {
    let disposed = false;
    const force = forceNext.current;
    forceNext.current = false;
    setRefreshing(true);
    setFailure(null);
    marketInfoCache
      .load(market, force)
      .then((data) => {
        if (!disposed)
          setSelection((current) =>
            current.market === market ? selectMarket(market, data) : current,
          );
      })
      .catch((e) => {
        if (!disposed)
          setFailure({
            market,
            message: e instanceof Error ? e.message : "市场状态读取失败",
          });
      })
      .finally(() => {
        if (!disposed) setRefreshing(false);
      });
    return () => {
      disposed = true;
    };
  }, [market, refreshTick]);
  return (
    <Store.Provider
      value={{
        market,
        source,
        adjustment,
        info,
        setMarket,
        setSource,
        error,
        refreshMarket,
        refreshing,
      }}
    >
      {info ? (
        children
      ) : (
        <div className="min-h-screen space-y-4 bg-slate-950 p-4 text-slate-300 sm:p-6">
          <MarketBar />
          <div
            role={error ? "alert" : "status"}
            className="rounded-xl border border-slate-800 p-6 text-sm"
          >
            {error || `正在读取 ${market} 市场与缓存状态…`}
            {error && (
              <button
                className="ml-4 text-emerald-300 underline"
                onClick={refreshMarket}
              >
                重试
              </button>
            )}
          </div>
        </div>
      )}
    </Store.Provider>
  );
}
export function useMarket() {
  const value = useContext(Store);
  if (!value) throw new Error("MarketProvider missing");
  return value;
}
export function MarketBar() {
  const {
    market,
    source,
    adjustment,
    info,
    setMarket,
    setSource,
    error,
    refreshing,
    refreshMarket,
  } = useMarket();
  const current = info?.sources.find(
    (s) => s.source === source && s.adjustment === adjustment,
  );
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3"
      aria-label="市场与数据来源"
    >
      <div className="flex gap-1 rounded-xl bg-slate-900 p-1">
        {(
          [
            ["CN", "A 股 · CNY"],
            ["US", "美股 · USD"],
            ["HK", "港股 · HKD"],
          ] as [Market, string][]
        ).map(([code, label]) => (
          <button
            key={code}
            aria-pressed={market === code}
            onClick={() => {
              const url = new URL(location.href);
              url.search = "";
              history.replaceState(null, "", url.pathname);
              setMarket(code);
            }}
            className={`rounded-lg px-3 py-2 text-sm ${market === code ? "bg-emerald-500/20 text-emerald-200" : "text-slate-400 hover:text-white"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
        {info && info.sources.length > 0 ? (
          <>
            <select
              aria-label="行情数据来源"
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-slate-200"
              value={`${source}|${adjustment}`}
              onChange={(e) => {
                const [src, adj] = e.target.value.split("|");
                const url = new URL(location.href);
                url.searchParams.delete("source");
                url.searchParams.delete("adjustment");
                history.replaceState(null, "", url.pathname + url.search);
                setSource(src, adj);
              }}
            >
              {!current && (
                <option value={`${source}|${adjustment}`}>
                  {source} · 暂无缓存
                </option>
              )}
              {info.sources.map((s) => (
                <option
                  key={`${s.source}|${s.adjustment}`}
                  value={`${s.source}|${s.adjustment}`}
                >
                  {s.source === "legacy_mysql" ? "已导入行情" : s.source} ·{" "}
                  {(
                    {
                      forward: "前复权",
                      none: "不复权",
                      backward: "后复权",
                    } as Record<string, string>
                  )[s.adjustment] || s.adjustment}{" "}
                  · {s.symbols.toLocaleString()} 个标的 · {s.scan_count ?? 0}{" "}
                  次扫描
                </option>
              ))}
            </select>
            <span>
              缓存截止{" "}
              <b className="text-slate-200">{current?.max_date || "未知"}</b>
            </span>
          </>
        ) : (
          <span>
            {info
              ? "当前市场尚无行情，可通过 CLI 导入或同步。"
              : "正在读取市场状态…"}
          </span>
        )}
        {error && info && (
          <span role="status" className="text-amber-300">
            状态更新失败，保留上次读取结果
          </span>
        )}
        <button
          type="button"
          aria-label="刷新市场缓存状态"
          title="重新读取当前市场的缓存范围与扫描次数"
          disabled={refreshing}
          onClick={refreshMarket}
          className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-slate-100 disabled:opacity-40"
        >
          <RefreshCw
            className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
          />
        </button>
      </div>
    </div>
  );
}
