import { Suspense, lazy, useEffect, useState } from 'react';
import { fetchKline, fetchStockProfile, fetchStockSignals, realPortfolio, StockSignal } from './api';
import { KlineData, StockProfile } from './types';
import { RealAccount } from './realTypes';
import SelectionShell, { SelectionNavProps } from './SelectionShell';
import { useMarket } from './MarketContext';
import { STRATEGY_MAP } from './strategies';

const Plot = lazy(() => import('react-plotly.js'));

interface Props extends SelectionNavProps {
  stockCode: string;
  stockName: string | null;
  onBack: () => void;
  onPortfolio: () => void;
}

function fmt(n: number | null | undefined) {
  return n == null ? '—' : n.toLocaleString('zh-CN', { maximumFractionDigits: 4 });
}

export default function StockDetailPage({
  stockCode,
  stockName,
  onBack,
  onPortfolio,
  onHome,
  onScan,
  onScreener,
}: Props) {
  const { market, source } = useMarket();
  const [bars, setBars] = useState<KlineData[]>([]);
  const [profile, setProfile] = useState<StockProfile | null>(null);
  const [signals, setSignals] = useState<StockSignal[]>([]);
  const [accounts, setAccounts] = useState<RealAccount[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    Promise.all([
      fetchKline(stockCode, 260),
      fetchStockProfile(stockCode),
      fetchStockSignals(stockCode),
      realPortfolio(),
    ])
      .then(([nextBars, nextProfile, nextSignals, portfolio]) => {
        if (cancelled) return;
        setBars(nextBars);
        setProfile(nextProfile);
        setSignals(nextSignals);
        setAccounts(
          portfolio.accounts.filter(account =>
            account.snapshot?.positions.some(position => position.symbol === stockCode),
          ),
        );
      })
      .catch(err => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [stockCode, market, source]);

  const latest = bars[bars.length - 1];
  const currency = market === 'CN' ? 'CNY' : market === 'US' ? 'USD' : 'HKD';
  const marked = signals
    .map(signal => {
      const bar = bars.find(item => item.date === signal.date);
      return bar ? { ...signal, high: bar.high } : null;
    })
    .filter((item): item is StockSignal & { high: number } => item !== null);

  return (
    <SelectionShell onHome={onHome || onBack} onScan={onScan} onScreener={onScreener} onPortfolio={onPortfolio}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button aria-label="返回" onClick={onBack} className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-slate-300">←</button>
          <div>
            <h1 className="text-2xl font-bold text-white">{profile?.name || stockName || stockCode}</h1>
            <p className="mt-1 text-sm text-slate-400">{stockCode} · {profile?.industry || '行业未记录'} · {currency}</p>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold text-slate-100">{fmt(latest?.close)} <span className="text-sm text-slate-400">{currency}</span></div>
          <p className="mt-1 text-xs text-slate-500">缓存收盘 · {latest?.date || '暂无行情'}</p>
        </div>
      </div>
      {error && <p role="alert" className="rounded-xl border border-red-500/30 p-4 text-red-300">{error}</p>}
      <section className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 p-4">
        <div className="mb-4 flex justify-between">
          <h2 className="font-semibold text-white">行情、均线与策略信号</h2>
          <span className="text-xs text-slate-500">{bars.length} 根日线 · {marked.length} 个信号 · {source}</span>
        </div>
        {loading ? <p className="p-10 text-center text-slate-400">正在加载真实行情…</p> : bars.length === 0 ? <p className="p-10 text-center text-slate-500">该市场 / 来源尚无该标的行情；不使用其他市场或模拟价格补齐。</p> : (
          <Suspense fallback={<p className="text-slate-400">正在加载图表…</p>}>
            <Plot
              data={[
                {
                  type: 'candlestick',
                  x: bars.map(bar => bar.date),
                  open: bars.map(bar => bar.open),
                  high: bars.map(bar => bar.high),
                  low: bars.map(bar => bar.low),
                  close: bars.map(bar => bar.close),
                  name: '日 K',
                  increasing: { line: { color: '#ef4444' } },
                  decreasing: { line: { color: '#10b981' } },
                },
                ...([5, 10, 20, 60] as const).map((period, index) => ({
                  type: 'scatter' as const,
                  mode: 'lines' as const,
                  x: bars.map(bar => bar.date),
                  y: bars.map(bar => bar[`ma${period}`] ?? null),
                  name: `MA${period}`,
                  line: { width: 1, color: ['#eab308', '#a78bfa', '#38bdf8', '#f97316'][index] },
                })),
                {
                  type: 'scatter',
                  mode: 'markers',
                  name: '策略信号',
                  x: marked.map(item => item.date),
                  y: marked.map(item => item.high * 1.01),
                  text: marked.map(item => item.strategies.map(name => STRATEGY_MAP[name]?.title ?? name).join('、')),
                  hovertemplate: '%{x}<br>%{text}<extra></extra>',
                  marker: { color: '#fbbf24', size: 11, symbol: 'triangle-up' },
                },
              ]}
              layout={{
                height: 520,
                autosize: true,
                paper_bgcolor: 'transparent',
                plot_bgcolor: 'transparent',
                font: { color: '#94a3b8' },
                margin: { l: 55, r: 20, t: 20, b: 40 },
                xaxis: { rangeslider: { visible: false }, type: 'category', gridcolor: '#1e293b', nticks: 10 },
                yaxis: { gridcolor: '#1e293b' },
                legend: { orientation: 'h', y: 1.06 },
              }}
              config={{ responsive: true, displaylogo: false }}
              style={{ width: '100%' }}
              useResizeHandler
            />
          </Suspense>
        )}
      </section>
      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-5">
        <h2 className="font-semibold text-white">信号记录</h2>
        {marked.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">当前来源没有与这批 K 线重叠的策略命中。信号只来自已保存的扫描，不会用别的行情源补点。</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {marked.slice().reverse().slice(0, 12).map(item => (
              <li key={item.date} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200">
                <span className="text-amber-300">{item.date}</span>
                <span className="mx-2 text-slate-500">共振 {item.resonanceCount}</span>
                {item.strategies.map(name => STRATEGY_MAP[name]?.title ?? name).join('、')}
                {item.reasons.length > 0 && <p className="mt-1 text-xs text-slate-400">{item.reasons.join('；')}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="rounded-2xl border border-slate-700 bg-slate-900 p-5">
        <div className="mb-4 flex justify-between">
          <h2 className="font-semibold text-white">该标的的真实持仓与条件单</h2>
          <button onClick={onPortfolio} className="text-sm text-cyan-300">查看全部账户 →</button>
        </div>
        {accounts.length === 0 ? <p className="text-sm text-slate-500">已保存的真实账户中未记录该标的。这里不会创建模拟仓位。</p> : accounts.map(account => {
          const position = account.snapshot!.positions.find(item => item.symbol === stockCode)!;
          const orders = account.snapshot!.orders.filter(item => item.symbol === stockCode);
          return (
            <div key={account.id} className="mb-3 rounded-xl border border-slate-700 p-4">
              <div className="flex flex-wrap justify-between gap-2 text-sm text-slate-200">
                <b>{account.label}</b>
                <span>{position.quantity} 股 · 成本 {position.average_cost || '未记录'} {position.currency}</span>
              </div>
              <p className="mt-2 text-xs text-slate-500">观察时间：{new Date(position.observed_at || account.snapshot!.as_of).toLocaleString('zh-CN')}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {orders.length ? orders.map((order, index) => (
                  <span key={index} className="rounded border border-slate-600 bg-slate-950 px-3 py-2 text-xs text-slate-300">
                    {order.order_kind === 'take_profit' ? '止盈' : order.order_kind === 'trailing' ? '移动条件单' : '止损 / 订单'}：{order.trigger_price || order.limit_price || (order.trailing_percent ? `${order.trailing_percent}%` : '未记录')} · {order.evidence === 'broker_verified' ? '券商快照' : order.evidence === 'manually_confirmed' ? '人工确认' : '待确认记录'}
                  </span>
                )) : <span className="text-xs text-amber-200">没有已保存的条件单，不能据此断言没有挂单。</span>}
              </div>
            </div>
          );
        })}
      </section>
    </SelectionShell>
  );
}
