import { useEffect, useState } from "react";
import { MarketInfo, openPath, useMarket } from "./MarketContext";
import { marketInfoCache } from "./marketInfoCache";

/** Explain an empty scope and offer explicit navigation to verified local data. */
export default function EmptyMarket() {
  const { market, info } = useMarket();
  const [available, setAvailable] = useState<MarketInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setAvailable([]);
    setLoading(true);
    setFailed(false);
    Promise.allSettled(
      (["CN", "HK", "US"] as const)
        .filter((m) => m !== market)
        .map((m) => marketInfoCache.load(m)),
    ).then((results) => {
      if (cancelled) return;
      setAvailable(results.flatMap((r) =>
        r.status === "fulfilled" && r.value.sources.length ? [r.value] : [],
      ));
      setFailed(results.some((r) => r.status === "rejected"));
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [market, retry]);
  return (
    <section className="tg-panel">
      <h2 className="tg-title">{info?.label || market}尚未导入行情</h2>
      <p className="mt-3 text-sm leading-7 text-slate-400">
        本地登记了 {info?.security_count || 0} 个证券，但没有日线价格，因此还不能生成这个市场的扫描结果或走势图。刷新页面不会补充行情。
      </p>
      <h3 className="mt-6 font-medium text-slate-200">查看已有数据</h3>
      {loading && <p className="tg-muted">正在查找已有行情的市场…</p>}
      {available.map((other) => {
        const scope = other.sources.find((s) =>
          s.source === other.default_source && s.adjustment === other.default_adjustment,
        ) || other.sources[0];
        const path = "/?" + new URLSearchParams({
          market: other.market, source: scope.source, adjustment: scope.adjustment,
        });
        return (
          <div key={other.market} className="mt-3 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-700 bg-slate-950/50 p-4">
            <div>
              <p className="font-semibold text-white">{other.label} · {scope.symbols.toLocaleString()} 个标的有行情</p>
              <p className="mt-2 text-xs text-slate-400">行情截至 {scope.max_date} · {scope.source} · 已保存 {scope.scan_count} 次扫描</p>
              {scope.latest_scan_date && <p className="mt-2 text-xs text-emerald-300">最近扫描：{scope.latest_scan_date}</p>}
            </div>
            <button className="tg-button" onClick={() => openPath(path)}>切换到{other.label}，查看结果 →</button>
          </div>
        );
      })}
      {!loading && !available.length && !failed && <p className="tg-muted">其他市场也没有可用行情。需先导入历史行情或同步明确标的。</p>}
      {failed && <p role="alert" className="tg-muted">部分市场查询失败。<button className="ml-2 text-cyan-300" onClick={() => setRetry((v) => v + 1)}>重试</button></p>}
      <details className="mt-6 text-sm text-slate-400">
        <summary className="cursor-pointer">如何补充{info?.label || market}行情？</summary>
        <p className="mt-3 leading-7">需要配置支持该市场的行情源，再同步你关注的具体股票。当前页面只读取已保存的行情，不会自动下载全市场数据；真实账户可从左侧“真实持仓”单独查看。</p>
      </details>
    </section>
  );
}
