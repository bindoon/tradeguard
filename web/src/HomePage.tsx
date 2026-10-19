import { MarketBar, useMarket } from './MarketContext';
interface HomePageProps {
  onScan?: () => void;
  onScreener?: () => void;
  onPortfolio?: () => void;
}

export default function HomePage({ onScan, onScreener, onPortfolio }: HomePageProps) {
  const {info, market} = useMarket();
  const menuItems = [
    {
      title: '每日扫描',
      subtitle: '查看每日扫描与共振结果',
      badge: 'SCAN',
      accent: 'emerald',
      onClick: onScan,
    },
    {
      title: '我的持仓',
      subtitle: '查看真实账户、条件单与更新时间',
      badge: 'BOOK',
      accent: 'blue',
      onClick: onPortfolio,
    },
    {
      title: '股票筛选器',
      subtitle: '按当前扫描同源条件筛选股票',
      badge: 'POOL',
      accent: 'cyan',
      onClick: onScreener,
    },
  ].filter(item => item.onClick);

  const accentClasses: Record<string, string> = {
    emerald: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:border-emerald-400/60 hover:bg-emerald-500/14',
    cyan: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:border-cyan-400/60 hover:bg-cyan-500/14',
    blue: 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:border-blue-400/60 hover:bg-blue-500/14',
    amber: 'border-amber-500/30 bg-amber-500/10 text-amber-300 hover:border-amber-400/60 hover:bg-amber-500/14',
  };

  return (
    <div className="min-h-screen overflow-x-hidden bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.16),transparent_28%),linear-gradient(135deg,#020617_0%,#0f172a_42%,#111827_100%)] px-3 py-3 sm:px-4 sm:py-4 lg:h-screen lg:overflow-hidden lg:px-5 lg:py-4 xl:px-6 xl:py-5">
      <div className="mx-auto flex min-h-[calc(100vh-1.5rem)] w-full min-w-0 flex-col gap-3 lg:h-full lg:min-h-0 lg:flex-row lg:gap-4 xl:gap-5">
        <aside className="w-full shrink-0 lg:w-[248px] xl:w-[264px] 2xl:w-[276px]">
          <div className="overflow-hidden rounded-[28px] border border-white/10 bg-slate-950/70 shadow-2xl shadow-black/30 backdrop-blur lg:flex lg:h-full lg:flex-col">
            <div className="border-b border-white/10 bg-gradient-to-br from-slate-900 via-slate-900 to-emerald-950/60 p-5">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-lg shadow-emerald-500/20">
                  <svg className="h-5 w-5 text-slate-950" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l5-5 4 4 7-8" />
                  </svg>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-[0.24em] text-emerald-300/80">TradeGuard Console</div>
                  <h1 className="mt-1 text-xl font-semibold tracking-tight text-white">股票研究与真实持仓</h1>
                </div>
              </div>

              <p className="text-sm leading-6 text-slate-300">
                按市场检查行情、执行扫描，并查看真实账户与条件单。
              </p>
            </div>

            <nav className="space-y-2 p-3">
              {menuItems.map(item => (
                <button
                  key={item.title}
                  onClick={item.onClick}
                  className={`w-full rounded-2xl border px-3.5 py-3 text-left transition-all ${accentClasses[item.accent]}`}
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-white">{item.title}</span>
                    <span className="rounded-full border border-current/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]">
                      {item.badge}
                    </span>
                  </div>
                  <p className="text-xs leading-5 text-slate-300">{item.subtitle}</p>
                </button>
              ))}
            </nav>

            <div className="border-t border-white/10 px-4 py-3">
              <p className="text-xs leading-5 text-slate-500">
                本系统仅用于研究和流程辅助，不构成任何投资建议。
              </p>
            </div>
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-x-hidden lg:-mr-5 lg:min-h-0 lg:overflow-y-auto lg:pr-5 xl:-mr-6 xl:pr-6">
          <div className="grid gap-4 pr-1 xl:grid-cols-[minmax(0,1.55fr)_minmax(260px,0.72fr)] xl:gap-5 2xl:grid-cols-[minmax(0,1.75fr)_minmax(300px,0.65fr)]">
            <div className="xl:col-span-2"><MarketBar /></div>
            <section className="overflow-hidden rounded-[30px] border border-white/10 bg-slate-950/60 shadow-2xl shadow-black/25 backdrop-blur">
              <div className="border-b border-white/10 bg-[linear-gradient(135deg,rgba(16,185,129,0.2),rgba(15,23,42,0.8)_45%,rgba(14,165,233,0.12))] px-6 py-8 sm:px-8 sm:py-10">
                <div className="mb-4 inline-flex items-center rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-emerald-200">
                  Daily Scan Workflow
                </div>
              </div>

              <div className="grid gap-4 p-6 sm:grid-cols-3 sm:p-8">
                <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-5">
                  <div className="text-xs uppercase tracking-[0.2em] text-emerald-200/80">Strategies</div>
                  <div className="mt-3 text-4xl font-semibold text-white">5</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">当前纳入每日共振扫描的核心策略数量。</p>
                </div>
                <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-5">
                  <div className="text-xs uppercase tracking-[0.2em] text-cyan-200/80">Cadence</div>
                  <div className="mt-3 text-4xl font-semibold text-white">Daily</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">默认扫描已有缓存，手动启动后可查看每个执行阶段。</p>
                </div>
                <div className="rounded-2xl border border-blue-500/20 bg-blue-500/10 p-5">
                  <div className="text-xs uppercase tracking-[0.2em] text-blue-200/80">Coverage</div>
                  <div className="mt-3 text-4xl font-semibold text-white">{info?.label || market}</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">市场独立记录交易日、币种、股票池和扫描历史。</p>
                </div>
              </div>
            </section>

            <section className="space-y-4 xl:space-y-6">
              <div className="rounded-[28px] border border-white/10 bg-slate-950/60 p-6 shadow-2xl shadow-black/25 backdrop-blur sm:p-7">
                <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Workspace Flow</div>
                <div className="mt-4 space-y-3">
                  <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">01. 更新数据</div>
                    <div className="mt-1 text-sm leading-6 text-slate-300">确认当前市场的数据来源和缓存截止日，再决定是否更新。</div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">02. 执行扫描</div>
                    <div className="mt-1 text-sm leading-6 text-slate-300">初筛、五策略打标、行业汇总；保存每次执行和跳过原因。</div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">03. 前端查看</div>
                    <div className="mt-1 text-sm leading-6 text-slate-300">查看扫描明细、行情图表与真实持仓；条件单保留人工或券商来源。</div>
                  </div>
                </div>
              </div>

              <div className="rounded-[28px] border border-white/10 bg-slate-950/60 p-6 shadow-2xl shadow-black/25 backdrop-blur sm:p-7">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-slate-400">System Focus</div>
                    <h3 className="mt-2 text-xl font-semibold text-white">当前系统重点</h3>
                  </div>
                  <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300">Daily Flow</div>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">股票池与扫描</div>
                    <div className="mt-1 text-sm leading-6 text-slate-300">查看每日命中策略、共振数量、行业分布与过程记录。</div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
                    <div className="text-sm font-semibold text-white">持仓与监控</div>
                    <div className="mt-1 text-sm leading-6 text-slate-300">按账户和币种查看真实持仓、已记录止盈止损及观察时间。</div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
