import { apiFetch } from "./api";
import { activeAdjustment, activeMarket, activeSource } from "./MarketContext";
export interface Pick {
  symbol: string;
  name: string | null;
  resonance_count: number;
  strategies_hit: string[];
  reasons: string[];
  close: string;
  sector_strength: number | null;
}
export interface DailyReport {
  trade_date: string;
  source: string;
  adjustment: string;
  status: string;
  run_id: string;
  market_regime: string;
  counts: {
    universe: number;
    scanned: number;
    hits: number;
    resonance: number;
  };
  top_resonance: Pick[];
  sector_strength_ranking: {
    sector: string;
    strength: number | null;
    hit_count: number;
  }[];
  changes_vs_previous_day: {
    previous_date: string | null;
    new_symbol_count: number;
    dropped_symbol_count: number;
    new_symbols: Pick[];
    dropped_symbols: { symbol: string; name: string | null }[];
    hit_delta: number | null;
  };
}
export interface Watch {
  id: string;
  symbol: string;
  name: string | null;
  currency: string;
  reason: string;
  source: string;
  adjustment: string;
  scan_run_id: string | null;
  created_at: string;
  close: string | null;
  price_date: string | null;
  signal_date: string | null;
  strategies: string[];
  resonance_count: number | null;
}
export interface Notice {
  id: string;
  kind: string;
  symbol: string | null;
  title: string;
  evidence: Record<string, unknown>;
  read: boolean;
  created_at: string;
}
export interface PriceRule {
  id: string;
  symbol: string;
  condition: "above" | "below";
  target_price: string;
  currency: string;
  active: boolean;
  source: string;
  adjustment: string;
}
export interface Review {
  account_label: string;
  symbol: string | null;
  name?: string | null;
  decision: "needs_input" | "review_exit" | "observe";
  reasons: string[];
  close?: string | null;
  price_date?: string | null;
  currency?: string;
  observed_at?: string;
  strategies?: string[];
}
export interface Profile {
  id: string;
  name: string;
  created_at: string;
  rules: Record<string, unknown>;
}
export interface CheckResult {
  check_id: string;
  rule_profile_id: string;
  snapshot_id: string | null;
  decision: string;
  blocked: string[];
  missing: string[];
  warnings: string[];
  metrics: Record<string, string>;
}
export interface Recommendation {
  scope: { market: "CN" | "US" | "HK"; source: string; adjustment: string };
  report_id: string;
  trade_date: string;
  author: string;
  methodology: string;
  summary: string;
  created_at: string;
  scan_status: string;
  limitations: string[];
  abstention_reason: string | null;
  picks: { rank: number; symbol: string; thesis: string; risks: string[]; invalidation: string; next_step: string; evidence_ids: string[]; evidence: Pick & { strategy_details: unknown[] } }[];
  alternatives: { symbol: string; reason: string }[];
}
export interface Workspace {
  recommendation: Recommendation | null;
  as_of: string;
  report: DailyReport | null;
  watchlist: Watch[];
  position_reviews: Review[];
  notifications: Notice[];
  profiles: Profile[];
  recent_checks: {
    id: string;
    symbol: string;
    created_at: string;
    rule_profile_id: string;
    snapshot_id: string | null;
    result: CheckResult;
  }[];
}
export function currentScope() {
  return {
    market: activeMarket(),
    source: activeSource(),
    adjustment: activeAdjustment(),
  };
}
export async function mutate<T>(
  path: string,
  method = "POST",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_URL || ""}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "操作失败，请检查输入或数据库迁移",
    );
  window.dispatchEvent(new Event("workspace-updated"));
  return data as T;
}
export const loadWorkspace = () => apiFetch<Workspace>("/api/workspace");
export const loadWatches = () => apiFetch<Watch[]>("/api/watchlist");
export const loadNotices = () => apiFetch<Notice[]>("/api/notifications");
export const loadAlerts = () => apiFetch<PriceRule[]>("/api/alerts");
export const saveWatch = (
  symbol: string,
  reason: string,
  scan_run_id?: string | null,
) =>
  mutate<{ id: string }>("/api/watchlist", "POST", {
    ...currentScope(),
    symbol,
    reason,
    scan_run_id: scan_run_id || null,
  });
export const deleteWatch = (id: string) =>
  mutate(`/api/watchlist/${encodeURIComponent(id)}`, "DELETE");
export const refreshNotices = () =>
  mutate("/api/notifications/refresh", "POST", currentScope());
export const readNotice = (id: string) =>
  mutate(`/api/notifications/${encodeURIComponent(id)}/read`);
export const createAlert = (
  symbol: string,
  condition: string,
  target_price: string,
) =>
  mutate("/api/alerts", "POST", {
    ...currentScope(),
    symbol,
    condition,
    target_price,
  });
export const cancelAlert = (id: string) =>
  mutate(`/api/alerts/${encodeURIComponent(id)}`, "DELETE");
export const searchStocks = (q: string) =>
  apiFetch<
    {
      symbol: string;
      name: string;
      industry: string | null;
      price_date: string | null;
      currency: string;
    }[]
  >(`/api/search?q=${encodeURIComponent(q)}`);
export const checkTrade = (
  profile_id: string,
  intent: Record<string, unknown>,
) =>
  mutate<CheckResult>("/api/discipline/check", "POST", { profile_id, intent });
export const decisionLabel: Record<string, string> = {
  needs_input: "先补证据",
  review_exit: "复核卖出计划",
  observe: "继续观察",
  pass: "已实现检查通过",
  blocked: "纪律拦截",
};
export const regimeLabel: Record<string, string> = {
  bull: "牛市",
  bear: "熊市",
  neutral: "震荡",
  unknown: "证据不足",
};
