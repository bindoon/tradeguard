import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
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
export function MarketProvider({ children }: { children: ReactNode }) {
  const [market, changeMarket] = useState<Market>(activeMarket);
  const [source, changeSource] = useState("");
  const [adjustment, changeAdjustment] = useState(activeAdjustment);
  const [info, setInfo] = useState<MarketInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  function setMarket(next: Market) {
    sessionStorage.setItem("tradeguard-market", next);
    changeMarket(next);
  }
  function setSource(next: string, adj = "forward") {
    sessionStorage.setItem("tradeguard-source-" + market, next);
    sessionStorage.setItem("tradeguard-adjustment-" + market, adj);
    changeSource(next);
    changeAdjustment(adj);
  }
  useEffect(() => {
    const readUrl = () => {
      const params = new URLSearchParams(location.search);
      const ticker = decodeURIComponent(
        location.pathname.split("/").pop() || "",
      );
      const requested =
        params.get("market") ||
        (location.pathname.startsWith("/stock/")
          ? ticker.endsWith(".US")
            ? "US"
            : ticker.endsWith(".HK")
              ? "HK"
              : "CN"
          : activeMarket());
      const selected: Market =
        requested === "US" || requested === "HK" ? requested : "CN";
      sessionStorage.setItem("tradeguard-market", selected);
      changeMarket(selected);
      const src = params.get("source");
      const adj = params.get("adjustment");
      if (src) {
        sessionStorage.setItem("tradeguard-source-" + selected, src);
        changeSource(src);
      }
      if (adj) {
        sessionStorage.setItem("tradeguard-adjustment-" + selected, adj);
        changeAdjustment(adj);
      }
    };
    readUrl();
    window.addEventListener("popstate", readUrl);
    return () => window.removeEventListener("popstate", readUrl);
  }, []);
  useEffect(() => {
    let disposed = false;
    sessionStorage.setItem("tradeguard-market", market);
    setLoading(true);
    setError(null);
    setInfo(null);
    fetch("/api/context?market=" + market)
      .then(async (r) => {
        if (!r.ok)
          throw new Error("无法读取市场数据，请检查本地服务与数据库迁移");
        return r.json() as Promise<MarketInfo>;
      })
      .then((data) => {
        if (disposed) return;
        setInfo(data);
        const saved = sessionStorage.getItem("tradeguard-source-" + market);
        const adj =
          sessionStorage.getItem("tradeguard-adjustment-" + market) ||
          "forward";
        const selected =
          data.sources.find(
            (s) => s.source === saved && s.adjustment === adj,
          ) ||
          data.sources.find(
            (s) =>
              s.source === data.default_source &&
              s.adjustment === data.default_adjustment,
          ) ||
          data.sources[0];
        // Preserve an explicit unavailable scope so a historical link cannot silently switch source.
        const params = new URLSearchParams(location.search);
        if (params.get("market") === market && params.get("source"))
          setSource(
            params.get("source")!,
            params.get("adjustment") || "forward",
          );
        else
          setSource(selected?.source || "", selected?.adjustment || "forward");
      })
      .catch((e) => {
        if (!disposed) setError(String(e.message));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [market]);
  return (
    <Store.Provider
      value={{ market, source, adjustment, info, setMarket, setSource, error }}
    >
      {loading ? (
        <div className="min-h-screen bg-slate-950 p-10 text-slate-300">
          正在读取 {market} 市场与缓存状态…
        </div>
      ) : error ? (
        <div
          role="alert"
          className="min-h-screen bg-slate-950 p-10 text-red-300"
        >
          {error}
          <button className="ml-4 underline" onClick={() => location.reload()}>
            重试
          </button>
        </div>
      ) : (
        children
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
  const { market, source, adjustment, info, setMarket, setSource } =
    useMarket();
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
            当前市场尚无行情。可通过 CLI 导入或同步，不填充其他市场数据。
          </span>
        )}
      </div>
    </div>
  );
}
