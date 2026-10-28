import WorkspaceChrome from "./WorkspaceChrome";
import {
  LayoutDashboard,
  Star,
  ScanLine,
  Wallet,
  SlidersHorizontal,
  Menu,
  X,
  TrendingUp,
} from "lucide-react";
import { openPath, scopedPath, MarketBar } from "./MarketContext";
import { ReactNode, useState } from "react";

export type SelectionSection =
  | "home"
  | "scan"
  | "screener"
  | "portfolio"
  | "monitor"
  | "watchlist"
  | "alerts";
export interface SelectionNavProps {
  onHome?: () => void;
  onScan?: () => void;
  onScreener?: () => void;
  onPortfolio?: () => void;
  onMonitor?: () => void;
}
interface Props extends SelectionNavProps {
  currentSection?: SelectionSection;
  children: ReactNode;
}

export default function SelectionShell({ currentSection, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const path = location.pathname;
  const active =
    currentSection ||
    (path.startsWith("/scan")
      ? "scan"
      : path.startsWith("/portfolio") || path === "/monitor"
        ? "portfolio"
        : path === "/watchlist"
          ? "watchlist"
          : path === "/screener"
            ? "screener"
            : path === "/alerts"
              ? "alerts"
              : path === "/"
                ? "home"
                : "stock");
  const items = [
    { key: "home", label: "每日工作台", path: "/", icon: LayoutDashboard },
    { key: "scan", label: "每日扫描", path: "/scan", icon: ScanLine },
    { key: "portfolio", label: "我的持仓", path: "/portfolio", icon: Wallet },
    {
      key: "screener",
      label: "股票筛选器",
      path: "/screener",
      icon: SlidersHorizontal,
    },
    { key: "watchlist", label: "我的自选", path: "/watchlist", icon: Star },
  ];
  const sidebar = (
    <>
      <button
        className="flex h-[72px] w-full shrink-0 items-center gap-3 border-b border-slate-200 px-5 text-left"
        onClick={() => {
          openPath(scopedPath("/"));
          setMenuOpen(false);
        }}
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white">
          <TrendingUp size={21} />
        </span>
        <span>
          <span className="block text-base font-semibold tracking-tight text-slate-900">
            TradeGuard
          </span>
          <span className="mt-0.5 block text-xs text-slate-500">
            投资研究工作台
          </span>
        </span>
      </button>
      <div className="px-5 pb-2 pt-6 text-[11px] font-medium tracking-wider text-slate-400">
        工作空间
      </div>
      <nav aria-label="主导航" className="flex-1 space-y-1 px-3 py-1">
        {items.map((item) => (
          <button
            key={item.key}
            aria-current={active === item.key ? "page" : undefined}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition ${active === item.key ? "bg-blue-50 font-semibold text-blue-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}
            onClick={() => {
              openPath(scopedPath(item.path));
              setMenuOpen(false);
            }}
          >
            <item.icon size={18} strokeWidth={active === item.key ? 2 : 1.7} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="border-t border-slate-200 px-5 py-4">
        <p className="text-xs leading-5 text-slate-500">本地个人工作台</p>
        <p className="mt-1 text-[11px] leading-5 text-slate-400">
          研究与纪律辅助 · 不自动下单
        </p>
      </div>
    </>
  );
  return (
    <div className="tg-page flex h-[100dvh] min-h-0 overflow-hidden text-slate-900">
      <aside className="hidden w-[220px] shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        {sidebar}
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-[80] lg:hidden">
          <button
            aria-label="关闭菜单遮罩"
            className="absolute inset-0 bg-slate-900/30"
            onClick={() => setMenuOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-[min(280px,85vw)] flex-col bg-white shadow-xl">
            {sidebar}
            <button
              aria-label="关闭菜单"
              className="absolute right-3 top-5 rounded-md p-2 text-slate-500"
              onClick={() => setMenuOpen(false)}
            >
              <X size={18} />
            </button>
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="z-30 shrink-0 border-b border-slate-200 bg-white">
          <div className="flex items-center border-b border-slate-100 px-3 sm:px-6">
            <button
              aria-label="打开菜单"
              className="mr-2 rounded-md p-2 text-slate-600 lg:hidden"
              onClick={() => setMenuOpen(true)}
            >
              <Menu size={20} />
            </button>
            <div className="min-w-0 flex-1">
              <MarketBar />
            </div>
          </div>
          <WorkspaceChrome key={location.pathname + location.search} />
        </header>
        <main
          aria-label="页面内容"
          className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-5 sm:px-6 sm:py-6 lg:px-7"
        >
          <div
            id="workspace-panel"
            role="tabpanel"
            aria-label="当前页面"
            tabIndex={0}
            className="mx-auto w-full max-w-[1680px] space-y-5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
