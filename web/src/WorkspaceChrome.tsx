import { useEffect, useRef, useState } from "react";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import { searchStocks } from "./workspaceApi";
import NotificationBell from "./NotificationBell";
type SearchResult = Awaited<ReturnType<typeof searchStocks>>;
type StockTab = { path: string; label: string };
const KEY = "tradeguard-stock-tabs-v1";
function savedTabs(): StockTab[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(value)
      ? value
          .filter(
            (x): x is StockTab =>
              !!x &&
              typeof x.path === "string" &&
              /^\/stock\/[A-Za-z0-9%._-]+\?/.test(x.path) &&
              typeof x.label === "string",
          )
          .slice(-10)
      : [];
  } catch {
    return [];
  }
}
export default function WorkspaceChrome() {
  const { market, source, adjustment } = useMarket();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tabs, setTabs] = useState<StockTab[]>(savedTabs);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!location.pathname.startsWith("/stock/")) return;
    const path = scopedPath(location.pathname + location.search);
    const label = decodeURIComponent(location.pathname.split("/").pop() || "");
    setTabs((current) => {
      const next = [
        ...current.filter((t) => t.path !== path),
        { path, label },
      ].slice(-10);
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* tabs remain available this visit */
      }
      return next;
    });
  }, [market, source, adjustment]);
  useEffect(() => {
    let cancelled = false;
    setResults([]);
    setError("");
    if (!query.trim() || !source) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      searchStocks(query)
        .then((data) => {
          if (!cancelled) setResults(data);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, market, source, adjustment]);
  function closeTab(path: string) {
    const next = tabs.filter((t) => t.path !== path);
    setTabs(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable */
    }
    if (location.pathname + location.search === path) openPath(scopedPath("/"));
  }
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <nav
          className="flex min-w-0 flex-1 gap-1 overflow-x-auto"
          aria-label="工作区标签"
        >
          <button className="tg-tab" onClick={() => openPath(scopedPath("/"))}>
            工作台
          </button>
          <button
            className="tg-tab"
            onClick={() => openPath(scopedPath("/watchlist"))}
          >
            自选
          </button>
          {tabs.map((t) => (
            <div
              className="tg-tab flex shrink-0 items-center gap-2"
              key={t.path}
            >
              <button onClick={() => openPath(t.path)} title={t.path}>
                {t.label}
              </button>
              <button
                aria-label={`关闭 ${t.label}`}
                onClick={() => closeTab(t.path)}
                className="text-slate-500 hover:text-white"
              >
                ×
              </button>
            </div>
          ))}
        </nav>
        <button className="tg-button shrink-0" onClick={() => setOpen(true)}>
          搜索股票{" "}
          <kbd className="ml-2 text-xs text-slate-500">⌘K / Ctrl+K</kbd>
        </button>
        <NotificationBell />
      </div>
      {open && (
        <div
          className="fixed inset-0 z-[60] bg-slate-950/80 p-4 pt-[10vh] backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label="搜索股票"
            className="mx-auto max-w-xl rounded-2xl border border-slate-600 bg-slate-900 p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Tab") {
                const nodes =
                  e.currentTarget.querySelectorAll<HTMLElement>("button,input");
                const first = nodes[0],
                  last = nodes[nodes.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <div className="mb-4 flex justify-between">
              <h2 className="font-semibold text-white">
                搜索 {market} 本地证券
              </h2>
              <button
                aria-label="关闭搜索"
                onClick={() => setOpen(false)}
                className="text-slate-400"
              >
                关闭 Esc
              </button>
            </div>
            <input
              ref={input}
              aria-label="股票代码或名称"
              placeholder="输入代码或名称"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="tg-input w-full"
            />
            <p className="my-3 text-xs text-slate-500">
              {source || "尚未选择来源"} · {adjustment} · 搜索不会联网下载行情
            </p>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {loading ? (
                <p className="tg-muted">搜索中…</p>
              ) : error ? (
                <p role="alert" className="text-red-300">
                  {error}
                </p>
              ) : results.length ? (
                results.map((r) => (
                  <button
                    key={r.symbol}
                    className="flex w-full items-center justify-between rounded-lg p-3 text-left text-slate-200 hover:bg-slate-800"
                    onClick={() => {
                      setOpen(false);
                      setQuery("");
                      openPath(
                        scopedPath("/stock/" + encodeURIComponent(r.symbol)),
                      );
                    }}
                  >
                    <span>
                      <b>{r.symbol}</b>　{r.name}
                      <small className="mt-1 block text-slate-500">
                        {r.industry || "行业未记录"}
                      </small>
                    </span>
                    <small className="text-slate-500">
                      {r.price_date || "本来源无行情"} · {r.currency}
                    </small>
                  </button>
                ))
              ) : (
                <p className="tg-muted">
                  {query ? "没有匹配的本地证券" : "输入股票代码或公司名称"}
                </p>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
