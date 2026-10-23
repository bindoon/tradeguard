import type { Market, MarketInfo } from "./MarketContext";

const FRESH_MS = 60_000;

export function createMarketInfoCache(
  fetchInfo: (market: Market) => Promise<MarketInfo>,
  clock = Date.now,
) {
  const saved = new Map<Market, { data: MarketInfo; at: number }>();
  const pending = new Map<Market, Promise<MarketInfo>>();
  return {
    peek(market: Market): MarketInfo | null {
      return saved.get(market)?.data ?? null;
    },
    load(market: Market, force = false): Promise<MarketInfo> {
      const cached = saved.get(market);
      if (!force && cached && clock() - cached.at < FRESH_MS)
        return Promise.resolve(cached.data);
      const active = pending.get(market);
      if (active) return active;
      const request = fetchInfo(market)
        .then((data) => {
          if (data.market !== market)
            throw new Error("市场状态与请求不符，请重试");
          saved.set(market, { data, at: clock() });
          return data;
        })
        .finally(() => pending.delete(market));
      pending.set(market, request);
      return request;
    },
  };
}

export const marketInfoCache = createMarketInfoCache(async (market) => {
  const response = await fetch("/api/context?market=" + market, {
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok)
    throw new Error("无法读取市场数据，请检查本地服务与数据库迁移");
  return response.json() as Promise<MarketInfo>;
});
