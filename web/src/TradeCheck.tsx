import { useEffect, useState } from "react";
import { realPortfolio } from "./api";
import { RealAccount } from "./realTypes";
import {
  checkTrade,
  CheckResult,
  decisionLabel,
  loadWorkspace,
  Profile,
} from "./workspaceApi";
import { useMarket } from "./MarketContext";
const reasonLabels: Record<string, string> = {
  portfolio_snapshot: "完整账户快照",
  fresh_portfolio_snapshot: "新鲜的账户快照",
  fresh_account_assets: "新鲜的账户资产",
  net_assets: "账户净资产",
  cash: "可用现金",
  margin_status: "杠杆状态",
  monthly_drawdown: "本月回撤",
  stop_price: "计划止损价格",
  manual_confirmation_of_stop_plan: "个人规则允许且人工确认的止损计划",
  single_stock_limit: "超出单股占比上限",
  max_trade_loss: "超出单次计划损失上限",
  insufficient_cash: "现金不足",
  leverage_forbidden: "规则禁止杠杆",
  trend_averaging_down: "趋势策略禁止摊低成本",
  use_add_for_existing_position: "已有持仓请选择加仓",
  existing_position_for_add: "加仓需要已有持仓",
  monthly_drawdown_circuit_breaker: "触发月度回撤熔断",
  pending_buy_orders_require_exposure_review: "待成交买单需复核敞口",
};
function explainReason(reason: string) {
  const [code, ...rest] = reason.split(":");
  const symbol = rest.join(":");
  const prefixes: Record<string, string> = {
    verified_stop_coverage: "缺少新鲜、足量的券商保护单证据",
    fresh_position: "持仓观察需要更新",
    manual_instrument_review: "需人工核验持仓类型与方向",
    fx: "缺少换汇到基准币种的汇率",
    value_add_requires_human_fundamental_review: "价值加仓需要人工复核基本面",
  };
  return (
    reasonLabels[reason] ||
    (prefixes[code]
      ? `${symbol ? symbol + "：" : ""}${prefixes[code]}`
      : reason)
  );
}
export default function TradeCheck({ symbol }: { symbol: string }) {
  const { market, source, adjustment } = useMarket();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [accounts, setAccounts] = useState<RealAccount[]>([]);
  const [profile, setProfile] = useState("");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError("");
    setProfile("");
    setLoading(true);
    Promise.all([loadWorkspace(), realPortfolio()])
      .then(([w, p]) => {
        if (!cancelled) {
          setProfiles(w.profiles);
          setAccounts(p.accounts);
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
  }, [symbol, market, source, adjustment]);
  return (
    <section className="tg-panel">
      <h2 className="tg-title">买入 / 加仓前 · 个人纪律检查</h2>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        输入你打算执行的交易。使用明确选择的规则版本和最新真实快照计算，不自动下单；策略命中只是研究依据。
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      {loading ? (
        <p className="tg-muted">正在读取规则版本与账户观察…</p>
      ) : !profiles.length ? (
        <p className="tg-muted">
          尚未导入个人规则。先通过{" "}
          <code>
            tradeguard discipline rules-import --file private/rules.json
          </code>{" "}
          导入你自己的规则；示例规则不会自动生效。
        </p>
      ) : (
        <form
          className="mt-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            setBusy(true);
            setError("");
            setResult(null);
            try {
              setResult(
                await checkTrade(String(f.get("profile_id")), {
                  account_id: f.get("account_id"),
                  symbol,
                  currency:
                    market === "CN" ? "CNY" : market === "US" ? "USD" : "HKD",
                  action: f.get("action"),
                  style: f.get("style"),
                  quantity: f.get("quantity"),
                  price: f.get("price"),
                  stop_price: f.get("stop_price") || null,
                  stop_evidence:
                    f.get("confirmed") === "on"
                      ? "manually_confirmed"
                      : "planned",
                  fees: f.get("fees") || "0",
                  thesis: f.get("thesis"),
                }),
              );
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <label className="text-xs text-slate-400">
              规则版本
              <select
                name="profile_id"
                required
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
                className="tg-input mt-1 w-full"
              >
                <option value="">请选择个人规则</option>
                {profiles.map((p) => (
                  <option value={p.id} key={p.id}>
                    {p.name} · {new Date(p.created_at).toLocaleString("zh-CN")}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-400">
              真实账户
              <select
                required
                name="account_id"
                defaultValue=""
                className="tg-input mt-1 w-full"
              >
                <option value="">请选择账户</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label} · {a.snapshot?.base_currency || "无快照"}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-400">
              动作
              <select name="action" className="tg-input mt-1 w-full">
                <option value="buy">新买入</option>
                <option value="add">加仓</option>
              </select>
            </label>
            <label className="text-xs text-slate-400">
              研究类型
              <select name="style" className="tg-input mt-1 w-full">
                <option value="trend">趋势交易</option>
                <option value="value">价值研究</option>
              </select>
            </label>
            {[
              ["quantity", "拟买数量"],
              ["price", "拟买价格"],
              ["stop_price", "计划止损价"],
              ["fees", "预计费用"],
            ].map(([name, label]) => (
              <label key={name} className="text-xs text-slate-400">
                {label}
                <input
                  name={name}
                  inputMode="decimal"
                  required={name === "quantity" || name === "price"}
                  placeholder={name === "fees" ? "0" : ""}
                  className="tg-input mt-1 w-full"
                />
              </label>
            ))}
          </div>
          {profile && (
            <details className="mt-3 text-xs text-slate-400">
              <summary className="cursor-pointer">查看选中的规则版本</summary>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3">
                {JSON.stringify(
                  profiles.find((p) => p.id === profile)?.rules,
                  null,
                  2,
                )}
              </pre>
            </details>
          )}
          <label className="mt-3 block text-xs text-slate-400">
            交易依据
            <textarea
              name="thesis"
              required
              minLength={1}
              rows={2}
              className="tg-input mt-1 w-full"
              placeholder="为什么现在买入，什么事实会使研究失效？"
            />
          </label>
          <label className="mt-3 flex gap-2 text-xs leading-5 text-slate-400">
            <input type="checkbox" name="confirmed" />
            我已人工确认止损计划（仍须规则允许；不代表已向券商挂单）
          </label>
          <button disabled={busy || !profile} className="tg-primary mt-4">
            {busy ? "检查中…" : "检查这笔拟交易"}
          </button>
        </form>
      )}
      {result && (
        <div
          role="status"
          className="mt-4 rounded-xl border border-slate-600 bg-slate-950 p-4"
        >
          <h3
            className={`font-semibold ${result.decision === "blocked" ? "text-red-300" : result.decision === "needs_input" ? "text-amber-300" : "text-emerald-300"}`}
          >
            {decisionLabel[result.decision] || result.decision}
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-slate-300">
            {[...result.blocked, ...result.missing].map((r) => (
              <li key={r}>· {explainReason(r)}</li>
            ))}
          </ul>
          <dl className="mt-3 flex flex-wrap gap-4 text-xs text-slate-400">
            {Object.entries(result.metrics).map(([k, v]) => (
              <div key={k}>
                {(
                  {
                    cost_base: "预计成本",
                    projected_stock_ratio: "交易后单股占比",
                    planned_loss_ratio: "计划损失占比",
                    base_currency: "账户币种",
                  } as Record<string, string>
                )[k] || k}
                : {v}
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-slate-500">
            检查编号 {result.check_id} · 规则版本 {result.rule_profile_id} ·
            快照 {result.snapshot_id || "缺失"}
            。通过仅代表已实现检查通过，不是下单授权。
          </p>
        </div>
      )}
    </section>
  );
}
