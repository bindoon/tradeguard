import {
  activeMarket,
  activeSource,
  activeAdjustment,
  type Market,
} from "./MarketContext";
import {
  KlineData,
  ScanSummary,
  ScanResult,
  ScanSector,
  ScanTopSector,
  FilteredPoolResult,
  StockProfile,
} from "./types";

// API base URL: 开发时通过 VITE_API_URL 指定后端地址，编译后留空则同域
const API_BASE = (import.meta.env.VITE_API_URL as string) || "";

type ScanResultsResponse = {
  results?: ScanResult[];
  count?: number;
};

type ScanSectorsResponse = {
  scanDate?: string;
  marketRegime?: string | null;
  topSectors?: Array<string | Partial<ScanTopSector>>;
  sectorDetails?: Array<{
    sector?: string;
    candidateCount?: number;
    avgRS?: number;
    maxResonance?: number;
  }>;
  sectors?: ScanSector[];
};

type ScanSummaryPayload = Omit<ScanSummary, "topSectors"> & {
  topSectors?: Array<string | Partial<ScanTopSector>> | null;
};

function normalizeTopSectors(
  payload: Array<string | Partial<ScanTopSector>> | null | undefined,
): ScanTopSector[] {
  if (!Array.isArray(payload)) {
    return [];
  }

  return payload
    .map((item) => {
      if (typeof item === "string") {
        return { sector: item, rs: null, count: 0 };
      }
      if (!item || typeof item !== "object") {
        return null;
      }
      return {
        sector: item.sector ?? "",
        rs: typeof item.rs === "number" ? item.rs : null,
        count: typeof item.count === "number" ? item.count : 0,
      };
    })
    .filter((item): item is ScanTopSector => Boolean(item && item.sector));
}

function normalizeScanSummary<T extends ScanSummaryPayload>(
  payload: T,
): Omit<T, "topSectors"> & { topSectors: ScanTopSector[] } {
  return {
    ...payload,
    topSectors: normalizeTopSectors(payload.topSectors),
  };
}

const inFlight = new Map<string, Promise<unknown>>();
export async function apiFetch<T>(path: string): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (!url.searchParams.has("market"))
    url.searchParams.set("market", activeMarket());
  if (!url.searchParams.has("source") && activeSource())
    url.searchParams.set("source", activeSource());
  if (!url.searchParams.has("adjustment"))
    url.searchParams.set("adjustment", activeAdjustment());
  const key = url.toString();
  const pending = inFlight.get(key);
  if (pending) return pending as Promise<T>;
  const request = (async () => {
    const response = await fetch(key, { signal: AbortSignal.timeout(20000) });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(
        typeof body.detail === "string"
          ? body.detail
          : `读取失败 (${response.status})`,
      );
    }
    return response.json() as Promise<T>;
  })().finally(() => inFlight.delete(key));
  inFlight.set(key, request);
  return request;
}

function normalizeScanResults(
  payload: ScanResult[] | ScanResultsResponse,
): ScanResult[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (Array.isArray(payload.results)) {
    return payload.results;
  }
  return [];
}

function normalizeScanSectors(
  payload: ScanSector[] | ScanSectorsResponse,
): ScanSector[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (Array.isArray(payload.sectors)) {
    return payload.sectors;
  }
  if (Array.isArray(payload.sectorDetails)) {
    return payload.sectorDetails.map((detail) => ({
      industry: detail.sector ?? "",
      candidateCount: detail.candidateCount ?? 0,
      rsScore: detail.avgRS ?? null,
      stocks: [],
    }));
  }
  return [];
}

/** 获取 K 线数据（含均线），endDate 可选 */
export async function fetchKline(
  stockCode: string,
  days = 120,
  endDate?: string,
  source?: string,
  scope?: { market: Market; adjustment: string },
): Promise<KlineData[]> {
  const params = new URLSearchParams({ days: String(days) });
  if (endDate) params.set("endDate", endDate);
  if (source) params.set("source", source);
  if (scope) {
    params.set("market", scope.market);
    params.set("adjustment", scope.adjustment);
  }
  return apiFetch<KlineData[]>(`/api/kline/${stockCode}?${params.toString()}`);
}

export async function fetchStockProfile(
  stockCode: string,
  endDate?: string,
): Promise<StockProfile> {
  return apiFetch<StockProfile>(
    `/api/stocks/${encodeURIComponent(stockCode)}/profile${endDate ? `?endDate=${endDate}` : ""}`,
  );
}

export interface StockSignal {
  date: string;
  strategies: string[];
  resonanceCount: number;
  reasons: string[];
}

export async function fetchStockSignals(
  stockCode: string,
  endDate?: string,
): Promise<StockSignal[]> {
  return apiFetch<StockSignal[]>(
    `/api/stocks/${encodeURIComponent(stockCode)}/signals${endDate ? `?endDate=${endDate}` : ""}`,
  );
}

// ── Stock Pool Filter API ─────────────────────────────────────────────────────

/** 实时执行股票池初筛，参数与每日扫描的 filter_stock_pool 完全一致 */
export async function fetchFilteredStockPool(params: {
  filterSt?: boolean;
  filterNewStock?: boolean;
  filterLiquidity?: boolean;
  filterMarketCap?: boolean;
  filterSuspended?: boolean;
  filterLimit?: boolean;
  minAvgVolume?: number;
  minListedDays?: number;
  limitPct?: number;
  targetDate?: string;
}): Promise<FilteredPoolResult> {
  const q = new URLSearchParams();
  if (params.filterSt !== undefined)
    q.set("filter_st", String(params.filterSt));
  if (params.filterNewStock !== undefined)
    q.set("filter_new_stock", String(params.filterNewStock));
  if (params.filterLiquidity !== undefined)
    q.set("filter_liquidity", String(params.filterLiquidity));
  if (params.filterMarketCap !== undefined)
    q.set("filter_market_cap", String(params.filterMarketCap));
  if (params.filterSuspended !== undefined)
    q.set("filter_suspended", String(params.filterSuspended));
  if (params.filterLimit !== undefined)
    q.set("filter_limit", String(params.filterLimit));
  if (params.minAvgVolume !== undefined)
    q.set("min_avg_volume", String(params.minAvgVolume));
  if (params.minListedDays !== undefined)
    q.set("min_listed_days", String(params.minListedDays));
  if (params.limitPct !== undefined)
    q.set("limit_pct", String(params.limitPct));
  if (params.targetDate) q.set("target_date", params.targetDate);
  return apiFetch<FilteredPoolResult>(`/api/stock-pool/filter?${q.toString()}`);
}

// ── Scan API ──────────────────────────────────────────────────────────────────

export interface CachedScanDate {
  date: string;
  symbols: number;
}
export function fetchScanDates(): Promise<CachedScanDate[]> {
  return apiFetch("/api/scan/dates");
}

/** 所有扫描日期汇总（降序） */
export async function fetchScanSummaries(
  allSources = false,
): Promise<ScanSummary[]> {
  const data = await apiFetch<ScanSummaryPayload[]>(
    "/api/scan/summaries" + (allSources ? "?all_sources=true" : ""),
  );
  return data.map(normalizeScanSummary);
}

/** 某日扫描的完整摘要（市场环境、过滤统计） */
export async function fetchScanSummary(
  scanDate: string,
): Promise<ScanSummary & { found: boolean }> {
  const data = await apiFetch<ScanSummaryPayload & { found: boolean }>(
    `/api/scan/${scanDate}/summary`,
  );
  return normalizeScanSummary(data);
}

/** 某日扫描结果，支持 minResonance / industry 过滤 */
export async function fetchScanResults(
  scanDate: string,
  minResonance = 1,
  industry?: string,
): Promise<ScanResult[]> {
  const params = new URLSearchParams({ min_resonance: String(minResonance) });
  if (industry) params.set("industry", industry);
  const data = await apiFetch<ScanResult[] | ScanResultsResponse>(
    `/api/scan/${scanDate}/results?${params.toString()}`,
  );
  return normalizeScanResults(data);
}

/** 某日扫描的行业共振详情 */
export async function fetchScanSectors(
  scanDate: string,
): Promise<ScanSector[]> {
  const data = await apiFetch<ScanSector[] | ScanSectorsResponse>(
    `/api/scan/${scanDate}/sectors`,
  );
  return normalizeScanSectors(data);
}

export async function startScan(
  date: string,
): Promise<{ run_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/scan/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      date,
      market: activeMarket(),
      source: activeSource(),
      adjustment: activeAdjustment(),
    }),
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string" ? body.detail : "无法开始扫描",
    );
  return body;
}
export async function realPortfolio(): Promise<
  import("./realTypes").RealPortfolio
> {
  return apiFetch("/api/portfolio/accounts");
}
export async function syncRealAccount(
  id: string,
): Promise<{ status: string; error?: string }> {
  const response = await fetch(
    `${API_BASE}/api/portfolio/sync/${encodeURIComponent(id)}`,
    { method: "POST" },
  );
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "同步失败");
  return body;
}
