import { useMarket } from './MarketContext';
import { useState, useEffect } from 'react';
import { fetchScanSummaries, startScan } from './api';
import { ScanSummary } from './types';
import SelectionShell, { SelectionNavProps } from './SelectionShell';
import { DAILY_STRATEGIES as STRATEGIES } from './strategies';

interface Props extends SelectionNavProps {
  onBack: () => void;
  onSelectDate: (date: string) => void;
}

const REGIME_LABEL: Record<string, { text: string; color: string }> = {
  bull:    { text: '牛市', color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' },
  neutral: { text: '震荡', color: 'text-yellow-400  bg-yellow-400/10  border-yellow-400/30'  },
  unknown: { text: '未判断', color: 'text-slate-400 bg-slate-700 border-slate-600' },
  bear:    { text: '熊市', color: 'text-red-400     bg-red-400/10     border-red-400/30'     },
};

const REGIME_TOOLTIP: Record<string, string> = {
  bull: '计算规则：指数收盘价高于 MA20，且 MA20 近 5 日斜率为正。',
  neutral: '计算规则：指数未同时满足牛市或熊市条件，视为震荡环境。',
  bear: '计算规则：指数收盘价低于 MA20，且 MA20 近 5 日斜率为负。',
};

function formatCount(value: number | null | undefined) {
  return typeof value === 'number' ? value.toLocaleString() : '--';
}

export default function ScanPage({ onBack, onSelectDate, onHome, onScan, onScreener, onPortfolio, onMonitor }: Props) {
  const {market, source, info} = useMarket();
  const [runDate, setRunDate] = useState(() => info?.sources.find(s => s.source === source)?.max_date || '');
  const [starting, setStarting] = useState(false);
  async function launchScan() { setStarting(true); setError(null); try { const result=await startScan(runDate); onSelectDate(result.run_id); } catch(e) { setError((e as Error).message); } finally {setStarting(false);} }
  const [summaries, setSummaries] = useState<ScanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stepOpen, setStepOpen] = useState<Record<string, boolean>>({ '01': false, '03': false });
  const toggleStep = (n: string) => setStepOpen(prev => ({ ...prev, [n]: !prev[n] }));

  useEffect(() => {
    fetchScanSummaries()
      .then(data => { setSummaries(data); setLoading(false); })
      .catch(err => { setError(err.message); setLoading(false); });
  }, [market, source]);

  return (
    <SelectionShell
      currentSection="scan"
      onHome={onHome ?? onBack}
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
            <h1 className="text-2xl font-bold text-white">每日扫描记录</h1>
            <p className="text-slate-400 text-sm">{info?.label} · 共 {summaries.length} 次扫描</p>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-emerald-500/20 bg-slate-900 p-4">
          <label className="text-sm text-slate-300">扫描交易日<input aria-label="扫描交易日" type="date" value={runDate} onChange={e=>setRunDate(e.target.value)} className="ml-3 rounded-lg border border-slate-700 bg-slate-950 p-2 text-white" /></label>
          <button disabled={starting || !source || !runDate} onClick={launchScan} className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{starting ? '正在创建任务…' : '开始扫描缓存'}</button>
          <p className="text-xs text-slate-400">使用已保存行情，不自动下载全市场；每次执行单独保留记录。</p>
        </div>
        {/* Workflow hint */}
        <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-4 space-y-3">
          <div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">扫描流程</div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {/* Step 01 — 市场环境 (expandable) */}
            <div className="rounded-lg border border-slate-700 bg-slate-900/60">
              <button
                onClick={() => toggleStep('01')}
                className="w-full flex items-start gap-2 px-3 py-2.5 text-left"
              >
                <span className="mt-0.5 shrink-0 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold text-slate-400">01</span>
                <div className="flex-1">
                  <div className="text-xs font-semibold text-white">市场环境</div>
                  <p className="mt-0.5 text-[11px] leading-4 text-slate-500">{market === 'CN' ? '上证' : market === 'US' ? 'SPY' : '恒生 ETF'} MA20；缺基准数据时保留未知</p>
                </div>
                <svg className={`mt-1 h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform ${stepOpen['01'] ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {stepOpen['01'] && (
                <div className="border-t border-slate-700 px-3 pb-3 pt-2.5 space-y-1.5">
                  <div className="mb-1.5 text-[10px] uppercase tracking-[0.18em] text-slate-500">{market === 'CN' ? '000001.SH' : market === 'US' ? 'SPY.US' : '02800.HK'}</div>
                  <div className="flex items-center gap-2.5 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-2.5 py-2">
                    <span className="shrink-0 rounded border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">牛市</span>
                    <p className="text-[11px] leading-4 text-slate-400">收盘 &gt; MA20，且 MA20 近 5 日斜率为正</p>
                  </div>
                  <div className="flex items-center gap-2.5 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-2.5 py-2">
                    <span className="shrink-0 rounded border border-yellow-400/30 bg-yellow-400/10 px-2 py-0.5 text-[11px] font-semibold text-yellow-300">震荡</span>
                    <p className="text-[11px] leading-4 text-slate-400">未同时满足牛市或熊市条件</p>
                  </div>
                  <div className="flex items-center gap-2.5 rounded-lg border border-red-500/20 bg-red-500/5 px-2.5 py-2">
                    <span className="shrink-0 rounded border border-red-400/30 bg-red-400/10 px-2 py-0.5 text-[11px] font-semibold text-red-300">熊市</span>
                    <p className="text-[11px] leading-4 text-slate-400">收盘 &lt; MA20，且 MA20 近 5 日斜率为负</p>
                  </div>
                </div>
              )}
            </div>

            {/* Step 02 — 初筛股票池 (enriched inline) */}
            <div className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2.5">
              <div className="flex items-start gap-2 mb-2.5">
                <span className="mt-0.5 shrink-0 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold text-slate-400">02</span>
                <div>
                  <div className="text-xs font-semibold text-white">初筛股票池</div>
                  <p className="mt-0.5 text-[11px] leading-4 text-slate-500">进入策略前的过滤规则</p>
                </div>
              </div>
              <ul className="space-y-1 pl-0.5">
                {[
                  ...(market === 'CN' ? ['剔除 ST / *ST 股票'] : []),
                  '剔除停牌股票',
                  market === 'CN' ? '剔除上市不满 365 天新股（缺日期另提示）' : '校验上市历史 90 天（缺日期另提示）',
                  market === 'CN' ? '近 5 日日均成交额 ≥ 1 亿 CNY' : '近 5 日日均成交额 ≥ 2,000 万当地币',
                  ...(market === 'CN' ? ['剔除触及涨跌幅阈值的标的（按板块区分）'] : ['不套用 A 股 ST / 涨跌停规则']),
                ].map(item => (
                  <li key={item} className="flex items-center gap-1.5 text-[11px] text-slate-400">
                    <span className="h-1 w-1 rounded-full bg-slate-500 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            {/* Step 03 — 策略扫描 (expandable, default collapsed) */}
            <div className="rounded-lg border border-slate-700 bg-slate-900/60">
              <button
                onClick={() => toggleStep('03')}
                className="w-full flex items-start gap-2 px-3 py-2.5 text-left"
              >
                <span className="mt-0.5 shrink-0 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-bold text-slate-400">03</span>
                <div className="flex-1">
                  <div className="text-xs font-semibold text-white">策略扫描</div>
                  <p className="mt-0.5 text-[11px] leading-4 text-slate-500">{STRATEGIES.length} 个策略打标，记录共振数</p>
                </div>
                <svg className={`mt-1 h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform ${stepOpen['03'] ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {stepOpen['03'] && (
                <div className="border-t border-slate-700 px-3 pb-3 pt-2.5 space-y-1.5">
                  {STRATEGIES.map(strategy => (
                    <div key={strategy.name} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border border-slate-700 bg-slate-950/40 px-2.5 py-1.5">
                      <span className="text-[11px] font-semibold text-white">{strategy.title}</span>
                      <span className="text-[11px] text-slate-500">· {strategy.description}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-4 text-red-300 text-sm">{error}</div>
        )}

        {loading && (
          <div className="rounded-lg border border-slate-700 bg-slate-800 py-16 text-center text-white text-xl">加载中...</div>
        )}

        {summaries.length === 0 && !loading && !error && (
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-8 text-center">
            <p className="text-slate-400">暂无扫描数据，请先运行 上方「开始扫描缓存」</p>
          </div>
        )}

        {!loading && (
          <div className="space-y-2">
          {summaries.map(s => {
            const regime = REGIME_LABEL[s.marketRegime] ?? { text: s.marketRegime, color: 'text-slate-400 bg-slate-700 border-slate-600' };
            const topSectors = Array.isArray(s.topSectors) ? s.topSectors.slice(0, 3) : [];
            const totalStockCount = s.totalStockCount ?? s.tradableCount;
            const filteredOutCount = s.filteredOutCount ?? Math.max(totalStockCount - s.tradableCount, 0);
            const hitStockCount = s.hitStockCount ?? s.candidateCount;
            const hitIndustryCount = s.hitIndustryCount ?? 0;
            const resonanceIndustryCount = s.sectorCount ?? s.resonanceIndustryCount ?? 0;
            const metrics = [
              { label: '命中股票', value: formatCount(hitStockCount), tone: 'text-emerald-400' },
              { label: '≥2 共振', value: formatCount(s.candidateCount), tone: 'text-cyan-400' },
              { label: '涉及行业', value: formatCount(hitIndustryCount), tone: 'text-amber-300' },
              { label: '共振行业', value: formatCount(resonanceIndustryCount), tone: 'text-blue-400' },
            ];
            return (
              <button
                key={s.id}
                onClick={() => onSelectDate(s.id)}
                className="w-full rounded-xl border border-slate-700 bg-slate-800 p-4 text-left transition-all hover:border-slate-500 hover:bg-slate-750"
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0 flex-1 space-y-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="w-28 shrink-0 text-white font-semibold">{s.scanDate}</div><span className="rounded border border-slate-600 px-2 py-0.5 text-xs text-cyan-200">{s.status === 'success' ? '完成' : s.status === 'partial' ? '部分完成' : s.status === 'running' ? '扫描中' : s.status === 'queued' ? '排队中' : '失败'}</span><span className="text-xs text-slate-500">{new Date(s.executionDate || '').toLocaleString('zh-CN')}</span>
                      <span
                        title={REGIME_TOOLTIP[s.marketRegime] ?? '市场环境按指数相对 MA20 与均线斜率判断。'}
                        className={`cursor-help rounded border px-2 py-0.5 text-xs font-medium ${regime.color}`}
                      >
                        {regime.text}
                      </span>
                      <span className="text-sm text-slate-400">
                        股票池 {formatCount(totalStockCount)} 只，过滤 {formatCount(filteredOutCount)} 只后继续扫描 {formatCount(s.tradableCount)} 只
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                      {metrics.map(metric => (
                        <div key={metric.label} className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2.5">
                          <div className={`text-lg font-semibold ${metric.tone}`}>{metric.value}</div>
                          <div className="mt-1 text-xs text-slate-500">{metric.label}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-3 xl:block xl:text-right">
                    <div className="flex flex-wrap justify-end gap-2">
                      {topSectors.length > 0 ? topSectors.slice(0, 3).map(sec => (
                        <span key={sec.sector} className="rounded-full border border-slate-600 bg-slate-900/70 px-2.5 py-1 text-xs text-slate-300">
                          {sec.sector}
                        </span>
                      )) : (
                        <span className="text-xs text-slate-500">暂无重点行业</span>
                      )}
                    </div>
                    <div className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-500">
                      <span>查看当日明细</span>
                      <svg className="h-4 w-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
          </div>
        )}
      </div>
    </SelectionShell>
  );
}
