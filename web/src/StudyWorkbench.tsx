import { ReactNode, useEffect, useRef, useState } from "react";
import {
  Config,
  Experiment,
  Manifest,
  Plugin,
  StudyCase,
  StudyCaseReport,
  StudyConfig,
  money,
  mutate,
  percent,
  statusLabel,
  withCommon,
} from "./backtestApi";

const panel = "rounded-xl border border-slate-200 bg-white p-5";
const button =
  "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-50";
const input = "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm";

function parameterSummary(
  plugin: Plugin | undefined,
  values: Record<string, unknown>,
) {
  const fields = plugin?.parameters_schema?.properties as
    | Record<string, { title?: string }>
    | undefined;
  return (
    Object.entries({ ...plugin?.default_parameters, ...values })
      .map(
        ([key, value]) =>
          `${fields?.[key]?.title || key}：${value == null ? "未启用" : typeof value === "boolean" ? (value ? "是" : "否") : String(value)}`,
      )
      .join("；") || "无可调参数"
  );
}

export function useStudyDraft(scope: string) {
  const [cases, setCases] = useState<StudyCase[]>([]);
  const [mode, setMode] = useState<StudyConfig["mode"]>("comparison");
  const [name, setName] = useState("策略对比与资金组合");
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setCases([]);
    setEditing(null);
    setOpen(false);
  }, [scope]);
  function apply(config: Config, action: "case" | "common") {
    if (action === "common") {
      if (!cases.length) throw new Error("请先加入至少一个策略方案");
      setCases(
        cases.map((c) => ({ ...c, config: withCommon(c.config, config) })),
      );
    } else if (editing) {
      setCases(
        cases.map((c) =>
          c.key === editing
            ? { ...c, config: withCommon(config, cases[0].config) }
            : c,
        ),
      );
      setEditing(null);
    } else {
      if (cases.length >= 8) throw new Error("每次最多 8 个策略方案");
      setCases([
        ...cases,
        {
          key: crypto.randomUUID(),
          weight: "0.5",
          config: cases.length
            ? withCommon(config, cases[0].config)
            : structuredClone(config),
        },
      ]);
    }
    setOpen(true);
    setRevision((v) => v + 1);
  }
  return {
    cases,
    setCases,
    mode,
    setMode,
    name,
    setName,
    editing,
    setEditing,
    open,
    setOpen,
    revision,
    apply,
  };
}

export function StudyWorkbench({
  draft,
  plugins,
  onEdit,
  onStarted,
}: {
  draft: ReturnType<typeof useStudyDraft>;
  plugins: Plugin[];
  onEdit: (config: Config, key: string | null) => void;
  onStarted: (id: string) => void;
}) {
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Manifest | null>(null);
  const generation = useRef(0);
  const region = useRef<HTMLElement>(null);
  useEffect(() => {
    generation.current++;
    setChecked(null);
    setError("");
    setBusy(false);
    return () => {
      generation.current++;
    };
  }, [draft.cases, draft.mode, draft.name]);
  useEffect(() => {
    if (draft.open) region.current?.scrollIntoView({ block: "start" });
  }, [draft.open, draft.revision]);
  if (!draft.open) return null;
  const base = draft.cases[0]?.config;
  async function submit(check: boolean) {
    const token = generation.current;
    setBusy(true);
    setError("");
    setChecked(null);
    try {
      if (draft.cases.length < 2) throw new Error("请先加入至少两个策略方案");
      const config: StudyConfig = {
        name: draft.name,
        mode: draft.mode,
        cases: draft.cases,
      };
      if (check) {
        const data = await mutate<{ manifest: Manifest }>(
          "/api/backtests/studies/preflight",
          config,
        );
        if (generation.current === token) setChecked(data.manifest);
      } else {
        const data = await mutate<{ id: string }>(
          "/api/backtests/studies",
          config,
        );
        if (generation.current === token) onStarted(data.id);
      }
    } catch (e) {
      if (generation.current === token)
        setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      if (generation.current === token) setBusy(false);
    }
  }
  return (
    <section
      ref={region}
      className={panel + " space-y-4"}
      aria-label="策略对比与资金组合配置"
    >
      <div className="flex flex-wrap justify-between gap-3">
        <h2 className="font-semibold">策略对比与资金组合</h2>
        <button className={button} onClick={() => draft.setOpen(false)}>
          收起研究配置
        </button>
      </div>
      <div role="tablist" aria-label="研究模式" className="flex gap-2">
        {(
          [
            ["comparison", "策略对比"],
            ["allocation", "资金组合"],
          ] as const
        ).map(([mode, title]) => (
          <button
            key={mode}
            role="tab"
            aria-selected={draft.mode === mode}
            className={
              button +
              (draft.mode === mode
                ? " !border-blue-600 !bg-blue-50 text-blue-700"
                : "")
            }
            onClick={() => draft.setMode(mode)}
          >
            {title}
          </button>
        ))}
      </div>
      <label className="block space-y-1 text-xs text-slate-600">
        <span>研究实验名称</span>
        <input
          className={input + " block w-full"}
          value={draft.name}
          maxLength={100}
          onChange={(e) => draft.setName(e.target.value)}
        />
      </label>
      <div className="rounded-lg bg-slate-50 p-3 text-xs leading-6 text-slate-600">
        <h3 className="font-semibold text-slate-900">① 共同设置</h3>
        {base ? (
          <>
            <p>
              {base.market} · {base.currency} · {base.source} /{" "}
              {base.adjustment} · {base.start} — {base.end} ·{" "}
              {base.symbols.length} 只股票
            </p>
            <p>
              {draft.mode === "allocation" ? "总初始资金" : "每套策略初始资金"}{" "}
              {money(base.initial_cash)} {base.currency}
              ；所有方案共用同一批冻结行情及成交假设。
            </p>
            <details>
              <summary className="cursor-pointer">股票池与成交假设明细</summary>
              <p className="break-all">{base.symbols.join(", ")}</p>
              <p>
                基准 {base.benchmark || "未知"}；佣金{" "}
                {base.execution.commission}；最低佣金{" "}
                {base.execution.minimum_commission} {base.currency}；卖出税{" "}
                {base.execution.sell_tax}；滑点 {base.execution.slippage_bps}{" "}
                bps；手数 {base.execution.lot_size}；结算等待{" "}
                {base.execution.settlement_days} 日；前日成交量比例{" "}
                {base.execution.prior_volume_fraction}；涨跌幅限制{" "}
                {base.execution.limit_pct || "未设置"}；缺日政策{" "}
                {base.missing_data === "error" ? "拒绝" : "跳过并标记"}。
              </p>
            </details>
            <button
              className={button + " mt-2"}
              onClick={() => onEdit(base, null)}
            >
              编辑共同设置
            </button>
          </>
        ) : (
          <p>
            从策略库选择策略，在回测表单填写股票池、日期、参数后，点击“加入对比
            / 组合”。第一个方案确定共同设置。
          </p>
        )}
      </div>
      <div className="text-xs leading-6 text-slate-600">
        <h3 className="font-semibold text-slate-900">
          ② 策略方案 · {draft.cases.length}/8
        </h3>
        <p>
          {draft.mode === "comparison"
            ? "各方案分别使用相同的初始资金与成交量额度，便于公平对比。"
            : "总资金按初始比例拆为独立子账本，成交量额度同步分摊；比例合计须不超过 100%，剩余持现金。各策略分别计费，不跨策略调拨、不净额撮合；仓位限制在各子策略内生效。"}
        </p>
        <p>
          加入后续方案时自动沿用共同设置；策略条件、参数、仓位、调仓与退出独立。草稿保留在当前页面，完成的报告入库保存。
        </p>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50">
            <tr>
              <th className="p-3">方案与条件</th>
              {draft.mode === "allocation" && (
                <th className="p-3">初始资金比例</th>
              )}
              <th className="p-3">操作</th>
            </tr>
          </thead>
          <tbody>
            {draft.cases.map((c) => (
              <tr key={c.key} className="border-b border-slate-100">
                <td className="p-3">
                  <p className="font-medium">{c.config.name}</p>
                  <p className="mt-1 text-slate-500">
                    {plugins.find((p) => p.name === c.config.portfolio_strategy)
                      ?.title || c.config.portfolio_strategy}{" "}
                    ·{" "}
                    {c.config.combination
                      ? `${c.config.combination.signals.length} 个信号 / ${c.config.combination.mode === "all" ? "全部命中" : c.config.combination.mode === "any" ? "任一命中" : `至少 ${c.config.combination.minimum} 个命中`}`
                      : "独立选股"}{" "}
                    ·{" "}
                    {{
                      daily: "每日评估",
                      weekly: "每周评估",
                      monthly: "每月评估",
                    }[c.config.schedule] || c.config.schedule}
                  </p>
                  <details className="mt-1 text-slate-500">
                    <summary className="cursor-pointer">
                      参数、仓位与退出
                    </summary>
                    <div className="mt-2 max-w-lg space-y-2 leading-6">
                      {c.config.combination?.signals.map((s) => (
                        <p key={s.name}>
                          {plugins.find((p) => p.name === s.name)?.title ||
                            s.name}
                          ：最近 {s.lookback} 个观察交易日内命中；
                          {parameterSummary(
                            plugins.find((p) => p.name === s.name),
                            s.parameters,
                          )}
                        </p>
                      ))}
                      <p>
                        交易策略参数：
                        {parameterSummary(
                          plugins.find(
                            (p) => p.name === c.config.portfolio_strategy,
                          ),
                          c.config.strategy_parameters,
                        )}
                      </p>
                      <p>
                        最多 {c.config.max_positions} 只持仓；单股目标上限{" "}
                        {percent(c.config.max_weight)}；可投资比例{" "}
                        {percent(c.config.invested_fraction)}。
                      </p>
                      <p>
                        额外退出：止损{" "}
                        {c.config.exits.stop_loss == null
                          ? "未设置"
                          : percent(c.config.exits.stop_loss)}
                        ；止盈{" "}
                        {c.config.exits.take_profit == null
                          ? "未设置"
                          : percent(c.config.exits.take_profit)}
                        ；跟踪{" "}
                        {c.config.exits.trailing_stop == null
                          ? "未设置"
                          : percent(c.config.exits.trailing_stop)}
                        ；持有期限 {c.config.exits.max_holding_days ?? "未设置"}
                        ；基础信号退出{" "}
                        {c.config.exits.signal_exit ? "开启" : "关闭"}
                        。未设置的退出不生效；交易策略还可自行退出。
                      </p>
                    </div>
                    <details className="mt-2">
                      <summary className="cursor-pointer">
                        高级配置 JSON
                      </summary>
                      <pre className="max-w-md overflow-auto whitespace-pre-wrap">
                        {JSON.stringify(
                          {
                            signals: c.config.combination,
                            parameters: c.config.strategy_parameters,
                            max_positions: c.config.max_positions,
                            max_weight: c.config.max_weight,
                            invested_fraction: c.config.invested_fraction,
                            rank_by: c.config.rank_by,
                            rebalance: c.config.rebalance,
                            exits: c.config.exits,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </details>
                </td>
                {draft.mode === "allocation" && (
                  <td className="p-3">
                    <label className="whitespace-nowrap">
                      <input
                        aria-label={c.config.name + "初始资金比例百分数"}
                        type="number"
                        min="0.01"
                        max="100"
                        step="0.01"
                        className={input + " w-24"}
                        value={
                          c.weight === ""
                            ? ""
                            : Number((Number(c.weight) * 100).toFixed(6))
                        }
                        onChange={(e) =>
                          draft.setCases(
                            draft.cases.map((row) =>
                              row.key === c.key
                                ? {
                                    ...row,
                                    weight:
                                      e.target.value === ""
                                        ? ""
                                        : (
                                            Number(e.target.value) / 100
                                          ).toFixed(6),
                                  }
                                : row,
                            ),
                          )
                        }
                      />{" "}
                      %
                    </label>
                  </td>
                )}
                <td className="p-3">
                  <div className="flex flex-wrap gap-2">
                    <button
                      className={button}
                      onClick={() => onEdit(c.config, c.key)}
                    >
                      载入编辑
                    </button>
                    <button
                      className={button}
                      aria-label={"移除" + c.config.name}
                      onClick={() => {
                        draft.setCases(
                          draft.cases.filter((r) => r.key !== c.key),
                        );
                        if (draft.editing === c.key) draft.setEditing(null);
                      }}
                    >
                      移除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {draft.mode === "allocation" && (
        <p className="text-xs text-slate-600">
          已分配{" "}
          {percent(
            draft.cases.reduce((total, c) => total + Number(c.weight || 0), 0),
          )}
          （显示值；服务端以精确小数校验）
        </p>
      )}
      <label className="flex gap-2 text-xs leading-6 text-amber-900">
        <input
          type="checkbox"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
        />
        <span>
          确认所有方案共用所列股票池、日期、价格模型与成交假设，结果用于本地研究。
        </span>
      </label>
      {checked && (
        <div
          role="status"
          className="rounded-lg bg-blue-50 p-3 text-xs leading-6 text-blue-900"
        >
          全部方案数据检查完成：{checked.calendar.length} 个观察日；同一输入
          SHA-256：{checked.input_hash}。
          {checked.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}
      {error && (
        <p
          role="alert"
          className="break-words rounded-lg bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          className={button}
          disabled={busy}
          onClick={() => void submit(true)}
        >
          检查全部方案
        </button>
        <button
          className={button + " !border-blue-600 !bg-blue-600 !text-white"}
          disabled={busy || !accepted}
          onClick={() => void submit(false)}
        >
          {busy
            ? "处理中…"
            : draft.mode === "comparison"
              ? "运行策略对比"
              : "运行资金组合"}
        </button>
      </div>
    </section>
  );
}

function Overlay({
  report,
}: {
  report: NonNullable<Experiment["study_report"]>;
}) {
  const lines = report.cases.map((c, i) => ({
    name: c.config.name,
    color: [
      "#2563eb",
      "#059669",
      "#d97706",
      "#9333ea",
      "#dc2626",
      "#0891b2",
      "#475569",
      "#db2777",
    ][i],
    values: c.report.curve.map(
      (p) => Number(p.equity) / Number(c.initial_cash),
    ),
  }));
  if (report.portfolio)
    lines.push({
      name: "资金组合",
      color: "#0f172a",
      values: report.portfolio.curve.map(
        (p) =>
          Number(p.equity) / Number(report.portfolio!.metrics.initial_cash),
      ),
    });
  const values = lines.flatMap((line) => line.values);
  let low = Math.min(1, ...values),
    high = Math.max(1, ...values);
  if (low === high) {
    low -= 0.01;
    high += 0.01;
  }
  return (
    <div>
      <svg
        role="img"
        aria-label="各策略归一化净值对比曲线"
        viewBox="0 0 900 240"
        className="w-full"
      >
        <path d="M65 20V200H880" fill="none" stroke="#cbd5e1" />
        <text x="5" y="25" fontSize="12">
          {high.toFixed(3)}
        </text>
        <text x="5" y="200" fontSize="12">
          {low.toFixed(3)}
        </text>
        {lines.map((line) => (
          <path
            key={line.name + line.color}
            d={line.values
              .map(
                (v, i) =>
                  `${i ? "L" : "M"}${65 + (815 * i) / Math.max(1, line.values.length - 1)},${200 - (180 * (v - low)) / (high - low)}`,
              )
              .join(" ")}
            fill="none"
            stroke={line.color}
            strokeWidth={line.name === "资金组合" ? 3 : 2}
          />
        ))}
        <text x="65" y="225" fontSize="12">
          {report.cases[0].report.curve[0].date}
        </text>
        <text x="880" y="225" textAnchor="end" fontSize="12">
          {
            report.cases[0].report.curve[
              report.cases[0].report.curve.length - 1
            ].date
          }
        </text>
      </svg>
      <div className="flex flex-wrap gap-4 text-xs">
        {lines.map((line) => (
          <span key={line.name + line.color} style={{ color: line.color }}>
            ● {line.name}
          </span>
        ))}
      </div>
    </div>
  );
}

export function StudyReport({
  experiment,
  renderCase,
}: {
  experiment: Experiment;
  renderCase: (c: StudyCaseReport) => ReactNode;
}) {
  const [selected, setSelected] = useState("");
  const report = experiment.study_report;
  if (!report)
    return (
      <section className={panel}>
        <h2 className="font-semibold">
          {experiment.name} ·{" "}
          {statusLabel[experiment.status] || experiment.status}
        </h2>
        {experiment.error && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {experiment.error}
          </p>
        )}
        <p className="mt-3 text-xs text-slate-600">
          所有方案完成后才发布完整报告。中断或失败不会展示成功的汇总收益。
        </p>
        <ol className="mt-3 space-y-2 text-xs text-slate-600">
          {experiment.events.map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ol>
      </section>
    );
  const active = report.cases.find((c) => c.key === selected);
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(experiment, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `strategy-study-${experiment.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-5">
      <section className={panel + " space-y-5"}>
        <div className="flex flex-wrap justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{experiment.name}</h2>
            <p className="mt-1 text-xs text-slate-500">
              {report.mode === "comparison"
                ? "策略对比 · 每套方案相同初始资金"
                : "资金组合 · 独立子账本按初始比例分配"}{" "}
              · {report.cases.length} 套方案 · {experiment.config.currency}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {experiment.config.start} — {experiment.config.end} ·{" "}
              {experiment.config.source} / {experiment.config.adjustment} ·{" "}
              {experiment.config.symbols.length} 只股票
            </p>
          </div>
          <button className={button} onClick={download}>
            导出研究报告 JSON
          </button>
        </div>
        {report.portfolio && (
          <div
            role="note"
            aria-label="资金组合汇总"
            className="rounded-lg bg-blue-50 p-3 text-sm leading-7 text-blue-900"
          >
            <p>
              组合累计收益 {percent(report.portfolio.metrics.total_return)} ·
              最大回撤 {percent(report.portfolio.metrics.max_drawdown)} ·
              期末权益 {money(report.portfolio.metrics.final_equity)}{" "}
              {experiment.config.currency}
            </p>
            <p>
              总费用 {money(report.portfolio.metrics.fees)}{" "}
              {experiment.config.currency} ·{" "}
              {report.portfolio.metrics.trade_count} 笔成交 · 未分配保留现金{" "}
              {money(report.reserved_cash)} {experiment.config.currency}
            </p>
          </div>
        )}
        <Overlay report={report} />
        <div className="overflow-auto">
          <table className="w-full whitespace-nowrap text-left text-xs">
            <thead className="bg-slate-50">
              <tr>
                {[
                  "方案",
                  "模拟初始资金",
                  "累计收益",
                  "最大回撤",
                  "费用",
                  "成交数",
                  "明细",
                ].map((t) => (
                  <th key={t} className="p-3">
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.cases.map((c) => (
                <tr key={c.key} className="border-b border-slate-100">
                  <td className="p-3">{c.config.name}</td>
                  <td className="p-3">
                    {money(c.initial_cash)} {c.config.currency}
                  </td>
                  <td className="p-3">
                    {percent(c.report.metrics.total_return)}
                  </td>
                  <td className="p-3">
                    {percent(c.report.metrics.max_drawdown)}
                  </td>
                  <td className="p-3">
                    {money(c.report.metrics.fees)} {c.config.currency}
                  </td>
                  <td className="p-3">{c.report.metrics.trade_count}</td>
                  <td className="p-3">
                    <button
                      className={button}
                      aria-label={"查看" + c.config.name + "完整报告"}
                      onClick={() => setSelected(c.key)}
                    >
                      完整报告
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!!report.attribution.length && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">各策略收益贡献</h3>
            <div className="overflow-auto">
              <table className="w-full whitespace-nowrap text-left text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    {["方案", "实际盈亏", "组合收益贡献", "期末资金比例"].map(
                      (t) => (
                        <th key={t} className="p-3">
                          {t}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {report.attribution.map((c) => (
                    <tr key={c.key}>
                      <td className="p-3">{c.name}</td>
                      <td className="p-3">
                        {money(c.profit)} {experiment.config.currency}
                      </td>
                      <td className="p-3">
                        {(Number(c.return_contribution) * 100).toFixed(2)}{" "}
                        个百分点
                      </td>
                      <td className="p-3">{percent(c.final_weight)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs leading-6 text-slate-500">
              收益贡献为各子账本实际盈亏 /
              总初始资金；贡献相加等于组合收益。期末资金比例包含各子账本自己的现金与持仓；未分配保留现金另计，不产生利息。初始比例不会自动恢复，各策略分别承担费用与分摊后的成交量额度。
            </p>
          </div>
        )}
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            日收益相关性与输入依据
          </summary>
          <div className="mt-3 space-y-2 text-xs leading-6 text-slate-600">
            {report.correlations.map((c) => (
              <p key={c.left + c.right}>
                {report.cases.find((r) => r.key === c.left)?.config.name} /{" "}
                {report.cases.find((r) => r.key === c.right)?.config.name}：
                {c.value == null
                  ? "未知（不足 20 个共同收益观察或收益无波动）"
                  : c.value.toFixed(3)}{" "}
                · {c.observations} 个共同收益观察
              </p>
            ))}
            <p className="break-all">
              同一行情输入 SHA-256：{report.input_hash}
            </p>
            <p className="break-all">结果 SHA-256：{report.result_hash}</p>
          </div>
        </details>
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            模型限制与共同数据清单
          </summary>
          <div className="mt-3 space-y-2 text-xs leading-6 text-slate-600">
            {(report.portfolio?.warnings || experiment.manifest.warnings).map(
              (w) => (
                <p key={w}>{w}</p>
              ),
            )}
            <pre className="overflow-auto">
              {JSON.stringify(experiment.manifest, null, 2)}
            </pre>
          </div>
        </details>
        {report.portfolio && (
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              组合期末持仓
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-6 text-slate-600">
              {report.portfolio.positions.length ? (
                report.portfolio.positions.map((p) => (
                  <p key={p.symbol}>
                    {p.symbol} · {p.quantity} 股 · {money(p.value)}{" "}
                    {experiment.config.currency}
                    {p.stale ? " · 估值陈旧" : ""}
                  </p>
                ))
              ) : (
                <p>期末无持仓</p>
              )}
            </div>
          </details>
        )}
      </section>
      {active && (
        <div>
          <div className="mb-3 flex justify-between">
            <h3 className="font-semibold">方案完整报告</h3>
            <button className={button} onClick={() => setSelected("")}>
              收起子报告
            </button>
          </div>
          {renderCase(active)}
        </div>
      )}
    </div>
  );
}
