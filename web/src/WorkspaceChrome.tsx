import { useEffect, useRef, useState } from "react";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import { searchStocks } from "./workspaceApi";
import NotificationBell from "./NotificationBell";
import { ChevronLeft, ChevronRight, Search, X, List } from "lucide-react";
import { apiFetch } from "./api";
import {
  adjacentTab,
  readStockTabs,
  StockTab,
  tabPath,
  visitStockTab,
} from "./stockTabs";
type SearchResult = Awaited<ReturnType<typeof searchStocks>>;
const KEY = "tradeguard-stock-tabs-v1";
function savedTabs(): StockTab[] {
  try {
    return readStockTabs(localStorage.getItem(KEY));
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
  const strip = useRef<HTMLDivElement>(null);
  const activeTab = useRef<HTMLButtonElement>(null);
  const activeGroup = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState({ left: false, right: false });
  const current = tabPath(location.pathname + location.search);
  const fixed = [
    { label: "工作台", path: "/" },
    { label: "每日扫描", path: "/scan" },
    { label: "自选", path: "/watchlist" },
  ];
  if (location.pathname === "/portfolio" || location.pathname === "/monitor")
    fixed.push({ label: "我的持仓", path: "/portfolio" });
  if (location.pathname === "/screener")
    fixed.push({ label: "股票筛选器", path: "/screener" });
  if (location.pathname === "/alerts")
    fixed.push({ label: "提醒记录", path: "/alerts" });
  function persist(next: StockTab[]) {
    setTabs(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* this visit */
    }
  }
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(tabs));
    } catch {
      /* this visit */
    }
  }, [tabs]);
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
    setTabs((items) => visitStockTab(items, path));
  }, [market, source, adjustment]);
  const missingNames = [
    ...new Set(tabs.filter((tab) => !tab.name).map((tab) => tab.label)),
  ].join(",");
  useEffect(() => {
    if (!missingNames) return;
    let cancelled = false;
    apiFetch<Record<string, string>>(
      "/api/securities/names?symbols=" + encodeURIComponent(missingNames),
    )
      .then((names) => {
        if (!cancelled)
          setTabs((items) =>
            items.map((tab) =>
              names[tab.label] ? { ...tab, name: names[tab.label] } : tab,
            ),
          );
      })
      .catch(() => {
        /* A name lookup never blocks stock navigation. */
      });
    return () => {
      cancelled = true;
    };
  }, [missingNames]);
  useEffect(() => {
    const node = strip.current;
    if (!node) return;
    const update = () =>
      setScroll({
        left: node.scrollLeft > 1,
        right: node.scrollLeft + node.clientWidth < node.scrollWidth - 1,
      });
    const observer = new ResizeObserver(update);
    observer.observe(node);
    node.addEventListener("scroll", update);
    activeGroup.current?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
    update();
    return () => {
      observer.disconnect();
      node.removeEventListener("scroll", update);
    };
  }, [tabs, current]);
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
    persist(next);
    if (current === path) openPath(adjacentTab(tabs, path) || scopedPath("/"));
  }
  return (
    <>
      <div className="flex min-w-0 items-center bg-slate-50">
        <button
          aria-label="向左滚动页签"
          disabled={!scroll.left}
          onClick={() =>
            strip.current?.scrollBy({ left: -300, behavior: "smooth" })
          }
          className="h-12 shrink-0 border-r border-slate-200 px-1 text-slate-500 hover:bg-white disabled:opacity-20"
        >
          <ChevronLeft size={18} />
        </button>
        <div
          ref={strip}
          role="tablist"
          aria-label="工作区标签"
          className="tg-tab-strip flex min-w-0 flex-1 overflow-x-auto"
          onKeyDown={(e) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
              return;
            const nodes = Array.from(
              e.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="tab"]',
              ),
            );
            const index = nodes.indexOf(
              document.activeElement as HTMLButtonElement,
            );
            if (index < 0) return;
            e.preventDefault();
            const target =
              e.key === "Home"
                ? 0
                : e.key === "End"
                  ? nodes.length - 1
                  : (index + (e.key === "ArrowRight" ? 1 : -1) + nodes.length) %
                    nodes.length;
            nodes[target]?.focus();
            nodes[target]?.scrollIntoView({
              block: "nearest",
              inline: "nearest",
            });
          }}
        >
          {fixed.map((tab) => {
            const selected =
              tab.path === "/scan"
                ? location.pathname.startsWith("/scan")
                : location.pathname === tab.path ||
                  (tab.path === "/portfolio" &&
                    location.pathname === "/monitor");
            return (
              <div
                className="tg-workspace-tab"
                ref={selected ? activeGroup : undefined}
                data-active={selected}
                key={tab.path}
              >
                <button
                  role="tab"
                  aria-controls="workspace-panel"
                  aria-selected={selected}
                  tabIndex={selected ? 0 : -1}
                  ref={selected ? activeTab : undefined}
                  className="h-12 whitespace-nowrap px-5 font-medium"
                  onClick={() => openPath(scopedPath(tab.path))}
                >
                  {tab.label}
                </button>
              </div>
            );
          })}
          {tabs.map((tab) => {
            const selected = current === tab.path;
            const date = new URL(tab.path, location.origin).searchParams.get(
              "endDate",
            );
            const label = tab.name || tab.label;
            return (
              <div
                className="tg-workspace-tab group"
                ref={selected ? activeGroup : undefined}
                data-active={selected}
                key={tab.path}
              >
                <button
                  role="tab"
                  aria-controls="workspace-panel"
                  aria-selected={selected}
                  tabIndex={selected ? 0 : -1}
                  ref={selected ? activeTab : undefined}
                  className="flex h-12 max-w-[230px] items-center gap-2 whitespace-nowrap pl-4 pr-1"
                  onClick={() => openPath(tab.path)}
                  title={`${label} · ${tab.label}${date ? " · 截至 " + date : ""}`}
                >
                  <span className="truncate font-medium">{label}</span>
                  {tab.name && (
                    <span className="text-[11px] text-slate-500">
                      {tab.label}
                    </span>
                  )}
                  {date && (
                    <span className="text-[10px] text-slate-400">
                      {date.slice(5)}
                    </span>
                  )}
                </button>
                <button
                  aria-label={`关闭 ${label}`}
                  onClick={() => closeTab(tab.path)}
                  className="mx-1 rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
        </div>
        <button
          aria-label="向右滚动页签"
          disabled={!scroll.right}
          onClick={() =>
            strip.current?.scrollBy({ left: 300, behavior: "smooth" })
          }
          className="h-12 shrink-0 border-l border-slate-200 px-1 text-slate-500 hover:bg-white disabled:opacity-20"
        >
          <ChevronRight size={18} />
        </button>
        <details className="relative shrink-0">
          <summary
            aria-label="所有股票页签"
            className="flex h-12 cursor-pointer list-none items-center px-3 text-slate-500 hover:bg-white"
          >
            <List size={18} />
          </summary>
          <div className="absolute right-0 top-full z-50 max-h-[65vh] w-72 overflow-y-auto rounded-b-lg border border-slate-200 bg-white p-2 shadow-lg max-sm:fixed max-sm:inset-x-4 max-sm:top-[140px] max-sm:w-auto">
            {tabs.length ? (
              <>
                <p className="px-3 py-2 text-xs text-slate-400">
                  已打开 {tabs.length} 个股票页签
                </p>
                {tabs.map((tab) => (
                  <button
                    key={tab.path}
                    className="block w-full rounded px-3 py-2 text-left text-sm text-slate-700 hover:bg-blue-50"
                    onClick={() => openPath(tab.path)}
                  >
                    {tab.name || tab.label}
                    <small className="ml-2 text-slate-400">
                      {tab.name ? tab.label : ""}
                    </small>
                  </button>
                ))}
                <button
                  className="mt-1 w-full border-t border-slate-100 px-3 py-2 text-left text-sm text-slate-500 hover:text-red-600"
                  onClick={() => {
                    persist([]);
                    if (current) openPath(scopedPath("/"));
                  }}
                >
                  关闭全部股票页签
                </button>
              </>
            ) : (
              <p className="p-3 text-sm text-slate-500">还没有打开股票</p>
            )}
          </div>
        </details>
        <div className="flex shrink-0 items-center gap-2 border-l border-slate-200 px-3">
          <button
            className="rounded-md p-2 text-slate-500 hover:bg-white hover:text-blue-700"
            aria-label="搜索股票"
            title="搜索股票（⌘K / Ctrl+K）"
            onClick={() => setOpen(true)}
          >
            <Search size={18} />
          </button>
          <NotificationBell />
        </div>
      </div>
      {open && (
        <div
          className="fixed inset-0 z-[60] bg-slate-50/80 p-4 pt-[10vh] backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-label="搜索股票"
            className="mx-auto max-w-xl rounded-2xl border border-slate-300 bg-white p-5 shadow-2xl"
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
              <h2 className="font-semibold text-slate-900">
                搜索 {market} 本地证券
              </h2>
              <button
                aria-label="关闭搜索"
                onClick={() => setOpen(false)}
                className="text-slate-500"
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
              搜索本地证券，输入代码或名称后选择股票打开。
            </p>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {loading ? (
                <p className="tg-muted">搜索中…</p>
              ) : error ? (
                <p role="alert" className="text-red-600">
                  {error}
                </p>
              ) : results.length ? (
                results.map((r) => (
                  <button
                    key={r.symbol}
                    className="flex w-full items-center justify-between rounded-lg p-3 text-left text-slate-700 hover:bg-slate-100"
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
