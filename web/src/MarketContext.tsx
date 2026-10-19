import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
export type Market = 'CN' | 'US' | 'HK';
export interface SourceInfo { source: string; adjustment: string; rows: number; symbols: number; min_date: string; max_date: string }
export interface MarketInfo { market: Market; label: string; currency: string; security_count: number; sources: SourceInfo[]; default_source: string; max_date: string | null; filter_defaults: Record<string, number | boolean> }
interface Context { market: Market; source: string; info: MarketInfo | null; setMarket: (market: Market) => void; setSource: (source: string) => void; error: string | null }
const Store = createContext<Context | null>(null);
export function activeMarket(): Market { const value = sessionStorage.getItem('tradeguard-market'); return value === 'US' || value === 'HK' ? value : 'CN'; }
export function activeSource() { return sessionStorage.getItem('tradeguard-source-' + activeMarket()) || ''; }
export function MarketProvider({ children }: { children: ReactNode }) {
  const [market, changeMarket] = useState<Market>(() => {
    const ticker = decodeURIComponent(location.pathname.split('/').pop() || '');
    if (location.pathname.startsWith('/stock/') && ticker.endsWith('.US')) return 'US';
    if (location.pathname.startsWith('/stock/') && ticker.endsWith('.HK')) return 'HK';
    return activeMarket();
  });
  const [source, changeSource] = useState('');
  const [info, setInfo] = useState<MarketInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  function setMarket(next: Market) { sessionStorage.setItem('tradeguard-market', next); setInfo(null); setLoading(true); changeMarket(next); }
  function setSource(next: string) { sessionStorage.setItem('tradeguard-source-' + market, next); changeSource(next); }
  useEffect(() => {
    let disposed = false;
    sessionStorage.setItem('tradeguard-market', market);
    setLoading(true); setError(null);
    fetch('/api/context?market=' + market).then(async r => { if (!r.ok) throw new Error('无法读取市场数据，请检查本地服务'); return r.json() as Promise<MarketInfo>; })
      .then(data => { if (disposed) return; setInfo(data); const saved = sessionStorage.getItem('tradeguard-source-' + market); const selected = data.sources.some(s => s.source === saved) ? saved! : data.default_source; sessionStorage.setItem('tradeguard-source-' + market, selected); changeSource(selected); })
      .catch(e => { if (!disposed) setError(String(e.message)); }).finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [market]);
  return <Store.Provider value={{ market, source, info, setMarket, setSource, error }}>
    {loading ? <div className="min-h-screen bg-slate-950 p-10 text-slate-300">正在读取 {market} 市场与缓存状态…</div> : error ? <div className="min-h-screen bg-slate-950 p-10 text-red-300">{error}<button className="ml-4 underline" onClick={() => location.reload()}>重试</button></div> : children}
  </Store.Provider>;
}
export function useMarket() { const value = useContext(Store); if (!value) throw new Error('MarketProvider missing'); return value; }
export function MarketBar() {
  const {market, source, info, setMarket, setSource} = useMarket();
  const current = info?.sources.find(s => s.source === source);
  return <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3" aria-label="市场与数据来源">
    <div className="flex gap-1 rounded-xl bg-slate-900 p-1">{([['CN','A 股 · CNY'],['US','美股 · USD'],['HK','港股 · HKD']] as [Market,string][]).map(([code,label]) => <button key={code} aria-pressed={market === code} onClick={() => setMarket(code)} className={`rounded-lg px-3 py-2 text-sm ${market === code ? 'bg-emerald-500/20 text-emerald-200' : 'text-slate-400 hover:text-white'}`}>{label}</button>)}</div>
    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
      {info && info.sources.length > 0 ? <><select aria-label="行情数据来源" className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-slate-200" value={source} onChange={e => setSource(e.target.value)}>{info.sources.map(s => <option key={s.source} value={s.source}>{s.source === 'legacy_mysql' ? '已导入行情' : s.source} · {s.symbols.toLocaleString()} 个标的</option>)}</select><span>缓存截止 <b className="text-slate-200">{current?.max_date}</b></span></> : <span>当前市场尚无行情。可通过 CLI 导入或同步；不会自动套用其他市场的数据。</span>}
    </div>
  </div>;
}
