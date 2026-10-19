import {useMarket} from './MarketContext';
import { startTransition, useState } from 'react';
import { fetchFilteredStockPool } from './api';
import { FilteredPoolStock } from './types';
import SelectionShell, { SelectionNavProps } from './SelectionShell';

interface Props extends SelectionNavProps {
  onBack: () => void;
  onSelectStock: (code: string, name: string | null) => void;
}

const PLACEHOLDER = null; void PLACEHOLDER;

interface FilterConfig {
  filterSt: boolean;
  filterNewStock: boolean;
  filterLiquidity: boolean;
  filterMarketCap: boolean;
  filterSuspended: boolean;
  filterLimit: boolean;
  minAvgVolumeYi: number;   // 单位：亿元
  minListedDays: number;
  limitPct: number;         // 百分比，如 9.5
}

const DEFAULTS: FilterConfig = {
  filterSt: true,
  filterNewStock: true,
  filterLiquidity: true,
  filterMarketCap: false,
  filterSuspended: true,
  filterLimit: true,
  minAvgVolumeYi: 1,
  minListedDays: 365,
  limitPct: 9.5,
};

const PAGE_SIZE = 200;

interface ToggleRowProps {
  label: string;
  desc: string;
  value: boolean;
  onChange: (v: boolean) => void;
}

function ToggleRow({ label, desc, value, onChange }: ToggleRowProps) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-700/60 last:border-0">
      <div>
        <div className="text-white text-sm font-medium">{label}</div>
        <div className="text-slate-500 text-xs mt-0.5">{desc}</div>
      </div>
      <button
        onClick={() => onChange(!value)}
        className={`relative rounded-full transition-colors shrink-0 flex items-center ${value ? 'bg-emerald-600' : 'bg-slate-600'}`}
        style={{ height: '22px', width: '40px' }}
      >
        <span
          className={`absolute rounded-full bg-white transition-transform shadow ${value ? 'translate-x-5' : 'translate-x-0.5'}`}
          style={{ height: '18px', width: '18px', top: '2px' }}
        />
      </button>
    </div>
  );
}

export default function ScreenerPage({ onBack, onSelectStock, onScan, onScreener, onPortfolio, onMonitor }: Props) {
  const {market,info} = useMarket();
  const [config, setConfig] = useState<FilterConfig>(() => ({...DEFAULTS,filterSt:market==='CN',filterLimit:market==='CN',minAvgVolumeYi:market==='CN'?1:0.2,minListedDays:market==='CN'?365:90}));
  const [baseResults, setBaseResults] = useState<FilteredPoolStock[]>([]);
  const [results, setResults] = useState<FilteredPoolStock[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [industryFilter, setIndustryFilter] = useState('');
  const [stockKeyword, setStockKeyword] = useState('');
  const [lastFetchKey, setLastFetchKey] = useState('');

  function set<K extends keyof FilterConfig>(key: K, value: FilterConfig[K]) {
    setConfig(prev => ({ ...prev, [key]: value }));
  }

  function buildFetchKey(nextConfig: FilterConfig) {
    return JSON.stringify({
      filterSt: nextConfig.filterSt,
      filterNewStock: nextConfig.filterNewStock,
      filterLiquidity: nextConfig.filterLiquidity,
      filterMarketCap: nextConfig.filterMarketCap,
      filterSuspended: nextConfig.filterSuspended,
      filterLimit: nextConfig.filterLimit,
      minAvgVolumeYi: nextConfig.minAvgVolumeYi,
      minListedDays: nextConfig.minListedDays,
      limitPct: nextConfig.limitPct,
    });
  }

  function applyClientFilters(stocks: FilteredPoolStock[], industryKeyword: string, keyword: string) {
    const industry = industryKeyword.trim();
    const normalizedKeyword = keyword.trim().toLowerCase();

    return stocks.filter(stock => {
      const matchesIndustry = industry
        ? stock.industry?.includes(industry)
        : true;

      if (!matchesIndustry) {
        return false;
      }

      if (!normalizedKeyword) {
        return true;
      }

      const normalizedCode = stock.code.toLowerCase();
      const normalizedName = (stock.name || '').toLowerCase();
      return normalizedCode.includes(normalizedKeyword) || normalizedName.includes(normalizedKeyword);
    });
  }

  async function runFilter(nextConfig: FilterConfig, industryKeyword: string, keyword: string) {
    const fetchKey = buildFetchKey(nextConfig);
    if (fetchKey === lastFetchKey && baseResults.length > 0) {
      const filtered = applyClientFilters(baseResults, industryKeyword, keyword);
      setVisibleCount(PAGE_SIZE);
      startTransition(() => {
        setResults(filtered);
      });
      setSearched(true);
      return;
    }

    setLoading(true);
    setError(null);
    setSearched(true);
    try {
      const data = await fetchFilteredStockPool({
        filterSt: nextConfig.filterSt,
        filterNewStock: nextConfig.filterNewStock,
        filterLiquidity: nextConfig.filterLiquidity,
        filterMarketCap: nextConfig.filterMarketCap,
        filterSuspended: nextConfig.filterSuspended,
        filterLimit: nextConfig.filterLimit,
        minAvgVolume: nextConfig.minAvgVolumeYi * 1e8,
        minListedDays: nextConfig.minListedDays,
        limitPct: nextConfig.limitPct / 100,
      });
      const filtered = applyClientFilters(data.stocks, industryKeyword, keyword);
      setTotal(data.total);
      setBaseResults(data.stocks);
      setLastFetchKey(fetchKey);
      setVisibleCount(PAGE_SIZE);
      startTransition(() => {
        setResults(filtered);
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '筛选失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleRun() {
    await runFilter(config, industryFilter, stockKeyword);
  }


  const visibleResults = results.slice(0, visibleCount);

  return (
    <SelectionShell
      currentSection="screener"
      onHome={onBack}
      onScan={onScan}
      onScreener={onScreener}
      onPortfolio={onPortfolio}
      onMonitor={onMonitor}
    >
      <div className="space-y-4">

        {/* Header */}
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 transition-all"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <h1 className="text-2xl font-bold text-white">股票筛选器</h1>
            <p className="text-slate-400 text-sm">与每日扫描一致的初筛条件，实时筛选可交易池</p>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)] gap-4">

          {/* Filter Panel */}
          <div className="space-y-3">
            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
              <h2 className="text-slate-300 font-semibold text-sm mb-3 uppercase tracking-wide">过滤开关</h2>
              {market==='CN' && <ToggleRow
                label="剔除 ST / *ST"
                desc="过滤名称含 ST 的股票"
                value={config.filterSt}
                onChange={v => set('filterSt', v)}
              />}
              <ToggleRow
                label="剔除次新股"
                desc={`上市不满 ${config.minListedDays} 天`}
                value={config.filterNewStock}
                onChange={v => set('filterNewStock', v)}
              />
              <ToggleRow
                label="流动性过滤"
                desc={`近5日日均成交额 ≥ ${config.minAvgVolumeYi} 亿 ${info?.currency}`}
                value={config.filterLiquidity}
                onChange={v => set('filterLiquidity', v)}
              />
              <ToggleRow
                label="剔除停牌"
                desc="当日成交量为零"
                value={config.filterSuspended}
                onChange={v => set('filterSuspended', v)}
              />
              {market==='CN' && <ToggleRow
                label="剔除涨跌停"
                desc={`涨/跌幅接近 ±${config.limitPct}%`}
                value={config.filterLimit}
                onChange={v => set('filterLimit', v)}
              />}
              <ToggleRow
                label="市值过滤"
                desc="当前缓存无可靠市值，启用后会提示数据缺口"
                value={config.filterMarketCap}
                onChange={v => set('filterMarketCap', v)}
              />
            </div>

            <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 space-y-3">
              <h2 className="text-slate-300 font-semibold text-sm mb-1 uppercase tracking-wide">阈值参数</h2>

              <div>
                <label className="text-slate-400 text-xs block mb-1">日均成交额门槛（亿 {info?.currency}）</label>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={config.minAvgVolumeYi}
                  onChange={e => set('minAvgVolumeYi', parseFloat(e.target.value) || 0)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="text-slate-400 text-xs block mb-1">次新股门槛（上市天数）</label>
                <input
                  type="number"
                  min="0"
                  step="30"
                  value={config.minListedDays}
                  onChange={e => set('minListedDays', parseInt(e.target.value) || 0)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>

              {market==='CN' && <div>
                <label className="text-slate-400 text-xs block mb-1">涨跌停判定阈值（%）</label>
                <input
                  type="number"
                  min="1"
                  max="25"
                  step="0.5"
                  value={config.limitPct}
                  onChange={e => set('limitPct', parseFloat(e.target.value) || 9.5)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none focus:border-emerald-500"
                />
                <p className="text-slate-600 text-xs mt-1">A股主板 9.5%，科创板/创业板 19.5%，北交所 29.5%</p>
              </div>}

              <div>
                <label className="text-slate-400 text-xs block mb-1">行业关键词（可选）</label>
                <input
                  type="text"
                  value={industryFilter}
                  onChange={e => setIndustryFilter(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleRun()}
                  placeholder="如：半导体"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <div>
                <label className="text-slate-400 text-xs block mb-1">股票名称 / 代码（可选）</label>
                <input
                  type="text"
                  value={stockKeyword}
                  onChange={e => setStockKeyword(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleRun()}
                  placeholder="如：宁德时代 / sz.300750 / 300750"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-white text-sm placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>
            </div>

            <button
              onClick={handleRun}
              disabled={loading}
              className="w-full py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold text-sm transition-all"
            >
              {loading ? '筛选中…' : '开始筛选'}
            </button>

            {!loading && searched && total !== null && (
              <p className="text-center text-slate-500 text-xs">
                初筛通过 <span className="text-slate-300 font-semibold">{total}</span> 只
                {(industryFilter.trim() || stockKeyword.trim()) ? `，本地过滤后 ${results.length} 只` : ''}
              </p>
            )}
          </div>

          {/* Results */}
          <div>
            {error && (
              <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-red-300 text-sm mb-3">{error}</div>
            )}

            {!error && !loading && searched && (
              <div className="mb-3 flex items-center justify-between text-xs text-slate-500">
                <span>
                  默认按每日扫描初筛条件加载
                  {total !== null ? `，通过 ${total} 只` : ''}
                  {(industryFilter.trim() || stockKeyword.trim()) ? `，本地过滤后 ${results.length} 只` : ''}
                </span>
                {results.length > PAGE_SIZE && (
                  <span>当前展示 {Math.min(visibleCount, results.length)} / {results.length}</span>
                )}
              </div>
            )}

            {!searched && !loading && (
              <div className="flex flex-col items-center justify-center h-64 text-slate-600">
                <svg className="w-12 h-12 mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <p className="text-sm">配置筛选条件后点击「开始筛选」</p>
              </div>
            )}

            {loading && (
              <div className="flex flex-col items-center justify-center h-64 text-slate-500">
                <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-3" />
                <p className="text-sm">正在筛选…</p>
              </div>
            )}

            {searched && !loading && results.length === 0 && !error && (
              <div className="flex items-center justify-center h-32 text-slate-600 text-sm">无符合条件的股票</div>
            )}

            {!loading && results.length > 0 && (
              <div className="space-y-2">
                {visibleResults.map(s => (
                  <div
                    key={s.code}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 hover:border-slate-500 cursor-pointer transition-all flex items-center gap-3"
                    onClick={() => onSelectStock(s.code, s.name)}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-semibold truncate">{s.name || s.code}</span>
                        <span className="text-slate-400 text-sm shrink-0">{s.code}</span>
                      </div>
                      {s.industry && (
                        <span className="text-xs text-slate-500 mt-0.5 block">{s.industry}</span>
                      )}
                    </div>
                    <svg className="w-4 h-4 text-slate-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                ))}
                {visibleCount < results.length && (
                  <button
                    onClick={() => setVisibleCount(prev => Math.min(prev + PAGE_SIZE, results.length))}
                    className="w-full py-3 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:border-slate-500 hover:text-white transition-all text-sm font-medium"
                  >
                    加载更多（再显示 {Math.min(PAGE_SIZE, results.length - visibleCount)} 只）
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

      </div>
    </SelectionShell>
  );
}
