import { useEffect, useState } from "react";
import SelectionShell, { SelectionNavProps } from "./SelectionShell";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import {
  cancelAlert,
  loadAlerts,
  loadNotices,
  Notice,
  PriceRule,
  readNotice,
  refreshNotices,
} from "./workspaceApi";
const labels: Record<string, string> = {
  trade_date: "行情交易日",
  price: "缓存收盘价",
  target_price: "提醒价格",
  condition: "比较方向",
  currency: "币种",
  mode: "观察类型",
  as_of: "快照观察时间",
  reason: "原因",
  strategies: "策略",
  run_id: "扫描批次",
};
export default function AlertsPage(props: SelectionNavProps) {
  const { market, source, adjustment } = useMarket();
  const [rows, setRows] = useState<Notice[]>([]);
  const [rules, setRules] = useState<PriceRule[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setRules([]);
    setError("");
    setLoading(true);
    if (!source) {
      setLoading(false);
      return;
    }
    Promise.all([loadNotices(), loadAlerts()])
      .then(([n, r]) => {
        if (!cancelled) {
          setRows(n);
          setRules(r);
        }
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
  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      setTick((t) => t + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <SelectionShell {...props} currentSection="alerts">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold text-slate-900">提醒记录</h1>
          <p className="mt-2 text-sm text-slate-500">
            价格条件、新策略信号与持仓待更新事项。
          </p>
        </div>
        <button
          disabled={busy || !source}
          className="tg-primary"
          onClick={() => act(refreshNotices)}
        >
          {busy ? "评估中…" : "评估当前缓存"}
        </button>
      </div>
      <div className="tg-panel text-sm leading-6 text-slate-500">
        只在手动评估或执行本地提醒命令时检查已保存的日线与快照。价格条件仅使用创建当日及之后的缓存收盘；旧历史行情不会触发新条件。不提供盘中连续监控，也不代表券商挂单或成交。
      </div>
      {error && (
        <p role="alert" className="tg-panel text-red-600">
          {error}
        </p>
      )}
      {loading ? (
        <p className="tg-muted">正在读取提醒…</p>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
          <section className="space-y-3">
            <h2 className="tg-title">
              收件箱 · {rows.filter((n) => !n.read).length} 条未读
            </h2>
            {!rows.length ? (
              <div className="tg-panel tg-muted">
                暂无触发记录。可在个股页创建价格条件，或刷新已有自选和账户快照的观察。
              </div>
            ) : (
              rows.map((n) => (
                <article
                  className={`tg-panel ${n.read ? "opacity-60" : ""}`}
                  key={n.id}
                >
                  <div className="flex flex-wrap justify-between gap-3">
                    <h3 className="font-semibold text-slate-900">{n.title}</h3>
                    <span className="text-xs text-slate-500">
                      {n.read ? "已读" : "未读"}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    记录时间 {new Date(n.created_at).toLocaleString("zh-CN")}
                  </p>
                  <dl className="mt-3 space-y-1 text-xs leading-5 text-slate-500">
                    {Object.entries(n.evidence)
                      .filter(
                        ([k]) => !["account_id", "snapshot_id"].includes(k),
                      )
                      .map(([k, v]) => (
                        <div className="break-words" key={k}>
                          <dt className="inline text-slate-500">
                            {labels[k] || k}：
                          </dt>
                          <dd className="inline">
                            {v === null
                              ? "未知"
                              : Array.isArray(v)
                                ? v.join("、")
                                : (
                                    {
                                      cached_close: "日线缓存收盘",
                                      saved_scan: "已保存策略扫描",
                                      above: "高于或等于",
                                      below: "低于或等于",
                                      older_than_24h: "观察已超过 24 小时",
                                      missing_snapshot: "缺少完整快照",
                                    } as Record<string, string>
                                  )[String(v)] || String(v)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                  <div className="mt-3 flex gap-4">
                    {n.symbol && (
                      <button
                        className="text-xs text-cyan-700"
                        onClick={() =>
                          openPath(
                            scopedPath(
                              "/stock/" + encodeURIComponent(n.symbol!),
                            ),
                          )
                        }
                      >
                        查看个股 →
                      </button>
                    )}
                    {!n.read && (
                      <button
                        disabled={busy}
                        className="text-xs text-slate-500"
                        onClick={() => act(() => readNotice(n.id))}
                      >
                        标为已读
                      </button>
                    )}
                  </div>
                </article>
              ))
            )}
          </section>
          <section className="tg-panel h-fit">
            <h2 className="tg-title">价格条件</h2>
            {!rules.length ? (
              <p className="tg-muted">在个股页设置高于或低于某价格的提醒。</p>
            ) : (
              rules.map((r) => (
                <div className="mt-4 rounded-xl bg-slate-50/60 p-3" key={r.id}>
                  <button
                    className="text-sm text-slate-700"
                    onClick={() =>
                      openPath(
                        scopedPath("/stock/" + encodeURIComponent(r.symbol)),
                      )
                    }
                  >
                    {r.symbol}
                  </button>
                  <p className="mt-2 text-sm text-slate-500">
                    收盘价 {r.condition === "above" ? "≥" : "≤"}{" "}
                    {r.target_price} {r.currency}
                  </p>
                  <div className="mt-2 flex justify-between text-xs text-slate-500">
                    <span>{r.active ? "等待评估" : "已触发 / 停用"}</span>
                    {r.active && (
                      <button
                        disabled={busy}
                        onClick={() => act(() => cancelAlert(r.id))}
                      >
                        停用
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </section>
        </div>
      )}
    </SelectionShell>
  );
}
