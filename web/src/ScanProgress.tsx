import {useEffect,useState} from 'react';
import {activeMarket} from './MarketContext';
interface Event {id:number;at:string;stage:string;message:string;completed:number|null;total:number|null}
interface State {status:string;events:Event[];skipped:{symbol:string;reason:string}[]}
const REASONS:Record<string,string>={missing_target_bar:'缺目标日行情',insufficient_history:'历史不足',low_liquidity:'成交额未达门槛',st_stock:'ST 股票',recent_listing:'上市时间不足',limit_move:'触及涨跌幅阈值',suspended_or_zero_volume:'停牌或零成交量'};
export default function ScanProgress({runId,onTerminal}:{runId:string;onTerminal?:()=>void}) {
 const [state,setState]=useState<State|null>(null);const [error,setError]=useState('');const [showSkipped,setShowSkipped]=useState(false);
 useEffect(()=>{let cancelled=false;let timer:ReturnType<typeof setTimeout>;let notified=false;
 const load=async()=>{try{const r=await fetch(`/api/scan/${encodeURIComponent(runId)}/events?market=${activeMarket()}`);if(!r.ok)throw new Error('过程记录暂时不可读');const d=await r.json() as State;if(cancelled)return;setState(d);setError('');if(['queued','running'].includes(d.status))timer=setTimeout(load,1200);else if(!notified){notified=true;onTerminal?.();}}catch(e){if(!cancelled){setError((e as Error).message);timer=setTimeout(load,3000);}}};load();return()=>{cancelled=true;clearTimeout(timer);};},[runId]);
 const last=state?.events.filter(e=>e.total).slice(-1)[0];const percent=last?.total?Math.round((last.completed||0)/last.total*100):0;
 return <section className="rounded-xl border border-slate-700 bg-slate-900/80 p-4" aria-label="本次扫描过程"><div className="mb-3 flex justify-between"><h2 className="font-semibold text-white">本次实际执行过程</h2><span className="text-xs text-emerald-300">{state?.status || '读取中'}</span></div>
 {error&&<p className="text-amber-300 text-sm">{error}</p>}{last&&<><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full bg-emerald-400 transition-all" style={{width:percent+'%'}} /></div><p className="mt-1 text-xs text-slate-500">已处理 {last.completed} / {last.total}</p></>}
 <ol className="mt-3 max-h-64 overflow-y-auto space-y-2">{state?.events.map(e=><li key={e.id} className="flex gap-3 text-xs"><time className="shrink-0 text-slate-500">{new Date(e.at).toLocaleTimeString('zh-CN')}</time><span className="text-slate-300">{e.message}</span></li>)}</ol>
 {state&&state.events.length===0&&<p className="text-sm text-slate-400">该历史批次未记录逐步日志；汇总和明细仍来自保存的数据。</p>}
 {!!state?.skipped.length&&<><button className="mt-3 text-xs text-cyan-300" onClick={()=>setShowSkipped(!showSkipped)}>{showSkipped?'收起':'查看'}过滤 / 缺失明细（{state.skipped.length}）</button>{showSkipped&&<div className="mt-2 max-h-48 overflow-y-auto text-xs text-slate-400">{state.skipped.map(s=><div key={s.symbol} className="flex justify-between border-b border-white/5 py-1"><span>{s.symbol}</span><span>{REASONS[s.reason]||s.reason}</span></div>)}</div>}</>}
 </section>;
}
