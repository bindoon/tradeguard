import { useEffect, useState } from "react";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import { deleteWatch, loadWatches, saveWatch, Watch } from "./workspaceApi";
import { STRATEGY_MAP } from "./strategies";
export default function WatchlistPage(props: SelectionNavProps) {
  const { market, source, adjustment } = useMarket();
  const [rows, setRows] = useState<Watch[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setError("");
    setLoading(true);
    if (!source) {
      setLoading(false);
      return;
    }
    loadWatches()
      .then((r) => {
        if (!cancelled) setRows(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [market, source, adjustment, tick]);
  return (
    <SelectionShell {...props} currentSection="watchlist">
      <h1 className="text-3xl font-semibold text-slate-900">我的自选</h1>
      <p className="text-sm text-slate-500">
        自选是研究队列，独立于真实持仓。按当前市场、来源和复权保存。
      </p>
      {error && (
        <p role="alert" className="tg-panel text-red-600">
          {error}
        </p>
      )}
      {loading ? (
        <p className="tg-muted">正在读取自选…</p>
      ) : !rows.length ? (
        <section className="tg-panel">
          <h2 className="tg-title">给下一次研究留下线索</h2>
          <p className="tg-muted">
            在全局搜索打开股票，或从扫描候选点击“加入自选”。记录关注原因，后续新信号会进入本地提醒。
          </p>
          <button className="tg-button" onClick={props.onScan}>
            查看每日扫描
          </button>
        </section>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {rows.map((row) => (
            <article key={row.id} className="tg-panel">
              <div className="flex flex-wrap justify-between gap-3">
                <button
                  className="tg-title"
                  onClick={() =>
                    openPath(
                      scopedPath("/stock/" + encodeURIComponent(row.symbol)),
                    )
                  }
                >
                  {row.name || row.symbol}{" "}
                  <span className="text-xs font-normal text-slate-500">
                    {row.symbol}
                  </span>
                </button>
                <span className="text-sm text-slate-600">
                  {row.close || "—"} {row.currency}
                </span>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                缓存收盘 {row.price_date || "暂无行情"} · {row.source} ·{" "}
                {row.adjustment}
              </p>
              <p className="mt-3 text-sm text-emerald-700">
                {row.signal_date
                  ? `${row.signal_date} · ${row.strategies.map((s) => STRATEGY_MAP[s]?.title || s).join("、")}`
                  : "当前来源尚无已保存信号"}
              </p>
              <form
                className="mt-4"
                onSubmit={async (e) => {
                  e.preventDefault();
                  const reason = new FormData(e.currentTarget).get(
                    "reason",
                  ) as string;
                  setBusy(row.id);
                  try {
                    await saveWatch(row.symbol, reason, row.scan_run_id);
                    setTick((t) => t + 1);
                  } catch (err) {
                    setError((err as Error).message);
                  } finally {
                    setBusy("");
                  }
                }}
              >
                <label className="text-xs text-slate-500">
                  观察原因与研究计划
                  <textarea
                    key={row.reason}
                    aria-label={`${row.symbol} 观察原因`}
                    name="reason"
                    maxLength={4000}
                    defaultValue={row.reason}
                    rows={3}
                    className="tg-input mt-2 w-full"
                  />
                </label>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button disabled={!!busy} className="tg-button">
                    {busy === row.id ? "保存中…" : "保存原因"}
                  </button>
                  {row.scan_run_id && (
                    <button
                      type="button"
                      className="text-xs text-cyan-700"
                      onClick={() =>
                        openPath(scopedPath("/scan/" + row.scan_run_id))
                      }
                    >
                      关联扫描 →
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={!!busy}
                    className="ml-auto text-xs text-slate-500 hover:text-red-600"
                    onClick={async () => {
                      setBusy(row.id);
                      try {
                        await deleteWatch(row.id);
                        setTick((t) => t + 1);
                      } catch (err) {
                        setError((err as Error).message);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    移出自选
                  </button>
                </div>
              </form>
              <p className="mt-3 text-xs text-slate-600">
                加入时间 {new Date(row.created_at).toLocaleString("zh-CN")}
              </p>
            </article>
          ))}
        </div>
      )}
    </SelectionShell>
  );
}
