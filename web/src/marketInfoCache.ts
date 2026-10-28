import type { Market, MarketInfo } from "./MarketContext";

const FRESH_MS = 60_000;
const STORAGE_KEY = "tradeguard-market-info-v1-";

type SavedInfo = { data: MarketInfo; at: number };

function browserStorage(): Storage | undefined {
  try {
    return typeof sessionStorage === "undefined" ? undefined : sessionStorage;
  } catch {
    return undefined;
  }
}

function validSavedInfo(value: SavedInfo, market: Market, now: number) {
  const data = value?.data;
  return (
    Number.isFinite(value?.at) &&
    value.at <= now &&
    now - value.at < 86_400_000 &&
    data?.market === market &&
    typeof data.security_count === "number" &&
    typeof data.default_source === "string" &&
    typeof data.default_adjustment === "string" &&
    typeof data.filter_defaults === "object" &&
    data.filter_defaults !== null &&
    Array.isArray(data.sources) &&
    data.sources.every(
      (s) =>
        typeof s.source === "string" &&
        typeof s.adjustment === "string" &&
        typeof s.rows === "number" &&
        typeof s.symbols === "number" &&
        typeof s.min_date === "string" &&
        typeof s.max_date === "string" &&
        typeof s.scan_count === "number" &&
        (s.latest_scan_date === null || typeof s.latest_scan_date === "string"),
    )
  );
}

export function createMarketInfoCache(
  fetchInfo: (market: Market, force: boolean) => Promise<MarketInfo>,
  clock = Date.now,
  storage = browserStorage(),
) {
  const saved = new Map<Market, SavedInfo>();
  const pending = new Map<Market, Promise<MarketInfo>>();
  function read(market: Market) {
    if (!saved.has(market)) {
      try {
        const value = JSON.parse(storage?.getItem(STORAGE_KEY + market) || "null");
        if (validSavedInfo(value, market, clock())) saved.set(market, value);
      } catch {
        // Disabled storage or an obsolete entry must not block the console.
      }
    }
    return saved.get(market);
  }
  return {
    peek(market: Market): MarketInfo | null {
      return read(market)?.data ?? null;
    },
    load(market: Market, force = false): Promise<MarketInfo> {
      const cached = read(market);
      if (!force && cached && clock() - cached.at < FRESH_MS)
        return Promise.resolve(cached.data);
      const active = pending.get(market);
      if (active) return active;
      const request = fetchInfo(market, force)
        .then((data) => {
          if (data.market !== market)
            throw new Error("市场状态与请求不符，请重试");
          const value = { data, at: clock() };
          saved.set(market, value);
          try {
            storage?.setItem(STORAGE_KEY + market, JSON.stringify(value));
          } catch {
            // Memory caching still works when browser storage is unavailable.
          }
          return data;
        })
        .finally(() => pending.delete(market));
      pending.set(market, request);
      return request;
    },
  };
}

export const marketInfoCache = createMarketInfoCache(async (market, force) => {
  const response = await fetch(
    "/api/context?market=" + market + (force ? "&refresh=true" : ""),
    { signal: AbortSignal.timeout(20_000) },
  );
  if (!response.ok)
    throw new Error("无法读取市场数据，请检查本地服务与数据库迁移");
  return response.json() as Promise<MarketInfo>;
});
