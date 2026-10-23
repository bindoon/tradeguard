import WorkspaceChrome from "./WorkspaceChrome";
import {
  LayoutDashboard,
  Star,
  Bell,
  ScanLine,
  Wallet,
  SlidersHorizontal,
} from "lucide-react";
import { openPath, scopedPath } from "./MarketContext";
import { MarketBar } from "./MarketContext";
import { ReactNode, useEffect, useState } from "react";

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

interface SelectionShellProps extends SelectionNavProps {
  currentSection?: SelectionSection;
  children: ReactNode;
}

function deriveSectionFromPath(pathname: string): SelectionSection | undefined {
  const cleanPath = pathname.replace(/\/+$/, "") || "/";
  if (cleanPath === "/") return "home";
  if (cleanPath === "/scan" || cleanPath.startsWith("/scan/")) return "scan";
  if (cleanPath === "/watchlist") return "watchlist";
  if (cleanPath === "/alerts") return "alerts";
  if (cleanPath === "/screener") return "screener";
  if (cleanPath === "/portfolio" || cleanPath.startsWith("/portfolio/"))
    return "portfolio";
  if (cleanPath === "/monitor" || cleanPath.startsWith("/monitor/"))
    return "portfolio";
  return undefined;
}

export default function SelectionShell({
  currentSection,
  onHome,
  onScan,
  onScreener,
  onPortfolio,
  children,
}: SelectionShellProps) {
  const activeSection =
    currentSection ?? deriveSectionFromPath(window.location.pathname);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [activeSection]);

  const menuItems = [
    {
      key: "home" as const,
      title: "每日工作台",
      subtitle: "候选、持仓复核与买卖检查",
      badge: "TODAY",
      accent: "emerald",
      onClick: () => openPath(scopedPath("/")),
    },
    {
      key: "watchlist" as const,
      title: "我的自选",
      subtitle: "跟进观察原因与策略信号",
      badge: "WATCH",
      accent: "cyan",
      onClick: () => openPath(scopedPath("/watchlist")),
    },
    {
      key: "alerts" as const,
      title: "提醒记录",
      subtitle: "价格条件与证据待更新",
      badge: "INBOX",
      accent: "blue",
      onClick: () => openPath(scopedPath("/alerts")),
    },
    {
      key: "scan" as const,
      title: "每日扫描",
      subtitle: "查看每日扫描与共振结果",
      badge: "SCAN",
      accent: "emerald",
      onClick: onScan,
    },
    {
      key: "portfolio" as const,
      title: "我的持仓",
      subtitle: "查看真实账户、止盈止损与更新时间",
      badge: "BOOK",
      accent: "blue",
      onClick: onPortfolio,
    },
    {
      key: "screener" as const,
      title: "股票筛选器",
      subtitle: "按当前扫描同源条件筛选股票",
      badge: "TOOL",
      accent: "cyan",
      onClick: onScreener,
    },
  ].filter((item) => item.onClick);

  const navIcons = {
    home: LayoutDashboard,
    watchlist: Star,
    alerts: Bell,
    scan: ScanLine,
    portfolio: Wallet,
    screener: SlidersHorizontal,
  };

  const sectionLabels: Record<SelectionSection, string> = {
    home: "每日工作台",
    watchlist: "我的自选",
    alerts: "提醒记录",
    scan: "每日扫描",
    screener: "股票筛选器",
    portfolio: "我的持仓",
    monitor: "持仓监控",
  };

  function renderSidebar(inDrawer = false) {
    return (
      <div
        className={`overflow-hidden rounded-2xl border border-white/10 bg-slate-950/70 shadow-2xl shadow-black/30 backdrop-blur ${inDrawer ? "h-full" : "lg:flex lg:h-full lg:flex-col"}`}
      >
        <div className="border-b border-white/10 bg-slate-900/50 p-4">
          <button
            type="button"
            onClick={() => {
              if (onHome) onHome();
              setMobileMenuOpen(false);
            }}
            className="w-full text-left"
            disabled={!onHome}
          >
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
                <svg
                  className="h-5 w-5 text-emerald-300"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16l5-5 4 4 7-8"
                  />
                </svg>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
                  TradeGuard Console
                </div>
                <h1 className="mt-1 text-base font-semibold tracking-tight text-white">
                  个人工作台
                </h1>
              </div>
            </div>
          </button>
        </div>

        <nav className="max-h-[50vh] space-y-1 overflow-y-auto p-2 lg:max-h-none lg:min-h-0 lg:flex-1">
          {menuItems.map((item) => {
            const isActive = item.key === activeSection;
            const Icon = navIcons[item.key];

            return (
              <button
                key={item.title}
                onClick={() => {
                  item.onClick?.();
                  setMobileMenuOpen(false);
                }}
                title={item.subtitle}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${isActive ? "bg-emerald-500/10 text-emerald-200" : "text-slate-400 hover:bg-slate-800/70 hover:text-slate-100"}`}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className={isActive ? "font-medium" : ""}>
                  {item.title}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="border-t border-white/10 px-4 py-3">
          <p className="text-xs leading-5 text-slate-500">
            本系统仅用于研究和流程辅助，不构成任何投资建议。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-slate-950 px-3 py-3 sm:px-4 sm:py-4 lg:h-screen lg:overflow-hidden lg:px-5 lg:py-4 xl:px-6 xl:py-5">
      <div className="mx-auto flex min-h-[calc(100vh-1.5rem)] w-full min-w-0 flex-col gap-3 lg:h-full lg:min-h-0 lg:flex-row lg:gap-4 xl:gap-5">
        <div className="lg:hidden">
          <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 shadow-xl shadow-black/20 backdrop-blur">
            <button
              type="button"
              onClick={() => onHome?.()}
              className="min-w-0 text-left"
            >
              <div className="text-[10px] uppercase tracking-[0.2em] text-emerald-300/80">
                TradeGuard Console
              </div>
              <div className="truncate text-sm font-semibold text-white">
                {activeSection
                  ? sectionLabels[activeSection]
                  : "股票研究与真实持仓"}
              </div>
            </button>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-200"
              aria-label="打开菜单"
            >
              <svg
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <button
              type="button"
              className="absolute inset-0 bg-slate-950/75 backdrop-blur-sm"
              onClick={() => setMobileMenuOpen(false)}
              aria-label="关闭菜单遮罩"
            />
            <div className="absolute inset-y-0 left-0 w-[88vw] max-w-[320px] p-3">
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  onClick={() => setMobileMenuOpen(false)}
                  className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-slate-900/90 text-slate-200"
                  aria-label="关闭菜单"
                >
                  <svg
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
              {renderSidebar(true)}
            </div>
          </div>
        )}

        <aside className="hidden shrink-0 lg:block lg:w-[200px] xl:w-[216px]">
          {renderSidebar()}
        </aside>

        <main className="min-w-0 flex-1 overflow-x-hidden lg:-mr-5 lg:min-h-0 lg:overflow-y-auto lg:pr-5 xl:-mr-6 xl:pr-6">
          <div className="w-full space-y-4 pr-1">
            <MarketBar />
            <WorkspaceChrome key={location.pathname + location.search} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
