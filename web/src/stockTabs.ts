export interface StockTab {
  path: string;
  label: string;
  name?: string;
}
const BASE = "http://tradeguard.local";

export function tabPath(path: string): string | null {
  try {
    const url = new URL(path, BASE);
    if (
      url.origin !== BASE ||
      !/^\/stock\/[A-Za-z0-9%._-]+$/.test(url.pathname)
    )
      return null;
    if (
      !/^[A-Za-z0-9._-]+$/.test(
        decodeURIComponent(url.pathname.split("/").pop() || ""),
      )
    )
      return null;
    if (!["CN", "US", "HK"].includes(url.searchParams.get("market") || ""))
      return null;
    const params = new URLSearchParams();
    for (const key of ["market", "source", "adjustment", "endDate"]) {
      const value = url.searchParams.get(key);
      if (value) params.set(key, value);
    }
    params.sort();
    return url.pathname + "?" + params;
  } catch {
    return null;
  }
}

export function readStockTabs(value: string | null): StockTab[] {
  try {
    const items: unknown = JSON.parse(value || "[]");
    if (!Array.isArray(items)) return [];
    return items
      .reduce<StockTab[]>((tabs, item) => {
        if (
          !item ||
          typeof item.path !== "string" ||
          typeof item.label !== "string"
        )
          return tabs;
        const path = tabPath(item.path);
        if (!path) return tabs;
        const tab: StockTab = {
          path,
          label: item.label,
          ...(typeof item.name === "string" && item.name
            ? { name: item.name }
            : {}),
        };
        return [...tabs.filter((t) => t.path !== path), tab];
      }, [])
      .slice(-10);
  } catch {
    return [];
  }
}

export function visitStockTab(tabs: StockTab[], path: string): StockTab[] {
  const normalized = tabPath(path);
  if (!normalized) return tabs;
  // Keep the user's tab order when revisiting an open stock.
  if (tabs.some((tab) => tab.path === normalized)) return tabs;
  const label = decodeURIComponent(
    new URL(normalized, BASE).pathname.split("/").pop() || "",
  );
  return [...tabs, { path: normalized, label }].slice(-10);
}

export function adjacentTab(tabs: StockTab[], closed: string): string | null {
  const index = tabs.findIndex((tab) => tab.path === closed);
  return tabs[index + 1]?.path || tabs[index - 1]?.path || null;
}
