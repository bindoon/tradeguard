import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { Play, RefreshCw, Settings2, Plus, Download } from "lucide-react";
import SelectionShell from "./SelectionShell";
import { StrategyLearning, StrategyParameters } from "./StrategyLearning";
import { openPath, scopedPath, useMarket } from "./MarketContext";
import {
  Config,
  CurvePoint,
  Experiment,
  ExperimentRow,
  Manifest,
  Plugin,
  loadExperiment,
  loadExperiments,
  loadPlugins,
  money,
  mutate,
  percent,
  reasonLabel,
  statusLabel,
} from "./backtestApi";

const panel = "rounded-xl border border-slate-200 bg-white p-5";
const input =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900";
const button =
  "inline-flex items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50";

function Field({ title, children }: { title: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5 text-xs text-slate-600">
      <span>{title}</span>
      {children}
    </label>
  );
}

function Chart({
  points,
  drawdown = false,
}: {
  points: CurvePoint[];
  drawdown?: boolean;
}) {
  const [cursor, setCursor] = useState<number | null>(null);
  const values = points.map((p) => Number(drawdown ? p.drawdown : p.equity));
  const benchmark =
    !drawdown && points.every((p) => p.benchmark_equity != null)
      ? points.map((p) => Number(p.benchmark_equity))
      : [];
  const all = [...values, ...benchmark, ...(drawdown ? [0] : [])];
  let min = Math.min(...all),
    max = Math.max(...all);
  if (min === max) {
    if (drawdown) min = max - 0.01;
    else {
      const padding = Math.abs(max) * 0.02 || 1;
      min -= padding;
      max += padding;
    }
  }
  const span = max - min;
  const x = (i: number) => 70 + (i * 780) / Math.max(1, points.length - 1);
  const y = (v: number) => 190 - ((v - min) / span) * 155;
  const path = (series: number[]) =>
    series.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const selected = points[cursor ?? points.length - 1];
  if (!selected) return null;
  return (
    <div>
      <div className="mb-2 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
        <span>
          {selected.date} ·{" "}
          {drawdown
            ? "回撤 " + percent(selected.drawdown)
            : "组合 " + money(selected.equity)}
          {!drawdown && selected.benchmark_equity != null
            ? " / 基准 " + money(selected.benchmark_equity)
            : ""}
        </span>
        {!drawdown && (
          <span>
            <span className="text-blue-600">— 组合</span>　
            <span>{benchmark.length ? "— 基准" : "基准：未知"}</span>
          </span>
        )}
      </div>
      <svg
        viewBox="0 0 900 235"
        role="img"
        aria-label={drawdown ? "组合回撤曲线" : "组合净值与基准曲线"}
        className="w-full touch-pan-y"
        onMouseLeave={() => setCursor(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          setCursor(
            Math.max(
              0,
              Math.min(
                points.length - 1,
                Math.round(
                  ((((e.clientX - rect.left) / rect.width) * 900 - 70) / 780) *
                    (points.length - 1),
                ),
              ),
            ),
          );
        }}
      >
        {[0, 0.5, 1].map((n) => (
          <g key={n}>
            <line
              x1="70"
              x2="850"
              y1={35 + n * 155}
              y2={35 + n * 155}
              stroke="#e2e8f0"
            />
            <text
              x="62"
              y={40 + n * 155}
              textAnchor="end"
              fill="#64748b"
              fontSize="12"
            >
              {drawdown
                ? percent(max - n * span)
                : money(String(max - n * span))}
            </text>
          </g>
        ))}
        {benchmark.length > 0 && (
          <polyline
            points={path(benchmark)}
            fill="none"
            stroke="#94a3b8"
            strokeWidth="2"
          />
        )}
        <polyline
          points={path(values)}
          fill="none"
          stroke={drawdown ? "#d97706" : "#2563eb"}
          strokeWidth="2.5"
        />
        {cursor != null && (
          <line
            x1={x(cursor)}
            x2={x(cursor)}
            y1="30"
            y2="195"
            stroke="#64748b"
            strokeDasharray="4 4"
          />
        )}
        <text x="70" y="222" fontSize="12" fill="#64748b">
          {points[0].date}
        </text>
        <text x="850" y="222" textAnchor="end" fontSize="12" fill="#64748b">
          {points[points.length - 1].date}
        </text>
      </svg>
    </div>
  );
}

function ExperimentForm({
  plugins,
  onStarted,
  choice,
}: {
  plugins: Plugin[];
  onStarted: (id: string) => void;
  choice: { plugin: Plugin; sequence: number } | null;
}) {
  const { market, source, adjustment, info } = useMarket();
  const end = info?.max_date || new Date().toISOString().slice(0, 10);
  const first = new Date(end + "T00:00:00Z");
  first.setUTCFullYear(first.getUTCFullYear() - 1);
  const [name, setName] = useState("组合回测");
  const [start, setStart] = useState(first.toISOString().slice(0, 10));
  const [finish, setFinish] = useState(end);
  const [symbols, setSymbols] = useState("");
  const [benchmark, setBenchmark] = useState("");
  const [selected, setSelected] = useState(["ma_golden_cross", "box_breakout"]);
  const [mode, setMode] = useState("all");
  const [minimum, setMinimum] = useState(2);
  const [portfolio, setPortfolio] = useState("signal_portfolio");
  const [parameterText, setParameterText] = useState("{}");
  const [lookbacks, setLookbacks] = useState<Record<string, number>>({});
  const [signalParameters, setSignalParameters] = useState<
    Record<string, string>
  >({});
  const [cash, setCash] = useState("100000");
  const [maxPositions, setMaxPositions] = useState(5);
  const [weight, setWeight] = useState("0.2");
  const [fraction, setFraction] = useState("0.95");
  const [rank, setRank] = useState("hits");
  const [schedule, setSchedule] = useState("daily");
  const [rebalance, setRebalance] = useState(false);
  const [missing, setMissing] = useState("error");
  const [commission, setCommission] = useState("0.0003");
  const [minCommission, setMinCommission] = useState("5");
  const [tax, setTax] = useState("0");
  const [slippage, setSlippage] = useState("5");
  const [lot, setLot] = useState(market === "CN" ? 100 : 1);
  const [settlement, setSettlement] = useState(market === "CN" ? 1 : 0);
  const [volume, setVolume] = useState("0.01");
  const [limit, setLimit] = useState("");
  const [stop, setStop] = useState("");
  const [profit, setProfit] = useState("");
  const [trailing, setTrailing] = useState("");
  const [days, setDays] = useState("");
  const [signalExit, setSignalExit] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preflight, setPreflight] = useState<Manifest | null>(null);
  const alive = useRef(true);
  const portfolioInfo = plugins.find((p) => p.name === portfolio);
  const usesSignals = portfolioInfo?.uses_signals !== false;
  useEffect(() => {
    if (!choice) return;
    const p = choice.plugin;
    setName("学习回测 · " + p.title);
    setPreflight(null);
    if (p.kind === "signal") {
      setPortfolio("signal_portfolio");
      setSelected([p.name]);
      setMode("all");
      setSignalParameters((v) => ({
        ...v,
        [p.name]: JSON.stringify(p.default_parameters || {}),
      }));
      setSignalExit(true);
    } else {
      setPortfolio(p.name);
      setParameterText(JSON.stringify(p.default_parameters || {}));
      setSignalExit(false);
      if (p.name === "turtle_daily") setSchedule("daily");
    }
  }, [choice]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  function build(): Config {
    if (usesSignals && !selected.length)
      throw new Error("请至少选择一个信号插件");
    return {
      name,
      market,
      currency: { CN: "CNY", US: "USD", HK: "HKD" }[market],
      source,
      adjustment,
      price_model:
        adjustment === "none" ? "raw_without_actions" : "adjusted_research",
      frequency: "1d",
      start,
      end: finish,
      symbols: symbols.split(/[\s,，;；]+/).filter(Boolean),
      benchmark: benchmark.trim() || null,
      initial_cash: cash,
      combination: usesSignals
        ? {
            mode,
            minimum: mode === "at_least" ? minimum : 1,
            signals: selected.map((name) => ({
              name,
              parameters: JSON.parse(signalParameters[name] || "{}"),
              lookback: lookbacks[name] || 1,
            })),
          }
        : null,
      portfolio_strategy: portfolio,
      strategy_parameters: JSON.parse(parameterText),
      max_positions: maxPositions,
      max_weight: weight,
      invested_fraction: fraction,
      rank_by: rank,
      schedule,
      rebalance,
      missing_data: missing,
      execution: {
        commission,
        minimum_commission: minCommission,
        sell_tax: tax,
        slippage_bps: slippage,
        lot_size: lot,
        settlement_days: settlement,
        prior_volume_fraction: volume,
        limit_pct: limit || null,
      },
      exits: {
        stop_loss: stop || null,
        take_profit: profit || null,
        trailing_stop: trailing || null,
        max_holding_days: days ? Number(days) : null,
        signal_exit: usesSignals && signalExit,
      },
    };
  }
  async function submit(e: FormEvent, checkOnly = false) {
    e.preventDefault();
    setError("");
    setPreflight(null);
    setBusy(true);
    try {
      const config = build();
      if (checkOnly) {
        const result = await mutate<{ manifest: Manifest }>(
          "/api/backtests/preflight",
          config,
        );
        if (alive.current) setPreflight(result.manifest);
      } else {
        const result = await mutate<{ id: string }>("/api/backtests", config);
        if (alive.current) onStarted(result.id);
      }
    } catch (e) {
      if (alive.current)
        setError(e instanceof Error ? e.message : "配置无法解析");
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const number = (
    value: string,
    setter: (v: string) => void,
    min = "0",
    max?: string,
  ) => (
    <input
      className={input}
      type="number"
      step="any"
      min={min}
      max={max}
      value={value}
      onChange={(e) => setter(e.target.value)}
      required
    />
  );
  return (
    <form
      className={panel + " space-y-5"}
      onSubmit={submit}
      onChange={() => setPreflight(null)}
      aria-label="新建回测实验"
    >
      <h2 className="text-base font-semibold">新建实验</h2>
      <p className="text-xs text-slate-500">
        {market} · {source || "未选择来源"} · {adjustment} · 日线 ·{" "}
        {market === "CN" ? "CNY" : market === "US" ? "USD" : "HKD"}
      </p>
      <Field title="实验名称">
        <input
          className={input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={100}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field title="开始日期">
          <input
            className={input}
            type="date"
            value={start}
            max={finish}
            onChange={(e) => setStart(e.target.value)}
            required
          />
        </Field>
        <Field title="结束日期">
          <input
            className={input}
            type="date"
            value={finish}
            max={end}
            onChange={(e) => setFinish(e.target.value)}
            required
          />
        </Field>
      </div>
      <Field title="固定股票池（逗号、空格或换行分隔，最多 500 只）">
        <textarea
          className={input}
          rows={3}
          placeholder={
            market === "CN"
              ? "600000.SH, 600519.SH"
              : market === "US"
                ? "AAPL.US, MSFT.US"
                : "00700.HK, 09988.HK"
          }
          value={symbols}
          onChange={(e) => setSymbols(e.target.value)}
          required
        />
      </Field>
      <Field title="基准代码（可选，必须同源同复权）">
        <input
          className={input}
          value={benchmark}
          onChange={(e) => setBenchmark(e.target.value)}
          placeholder="不填则基准为未知"
        />
      </Field>
      {usesSignals && (
        <>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">信号插件</legend>
            {plugins
              .filter((p) => p.kind === "signal")
              .map((p) => (
                <div
                  key={p.name}
                  className="rounded-lg border border-slate-200 p-3"
                >
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.includes(p.name)}
                      disabled={!p.enabled && !selected.includes(p.name)}
                      onChange={() =>
                        setSelected((v) =>
                          v.includes(p.name)
                            ? v.filter((n) => n !== p.name)
                            : [...v, p.name],
                        )
                      }
                    />
                    {p.title}
                    {!p.enabled && (
                      <span className="text-xs text-amber-700">已禁用</span>
                    )}
                  </label>
                  {selected.includes(p.name) && (
                    <details className="mt-2 text-xs text-slate-500">
                      <summary className="cursor-pointer">
                        参数与时序窗口
                      </summary>
                      <Field title="最近 N 个观察交易日内命中">
                        <input
                          className={input}
                          type="number"
                          min={1}
                          max={60}
                          value={lookbacks[p.name] || 1}
                          onChange={(e) =>
                            setLookbacks((v) => ({
                              ...v,
                              [p.name]: Number(e.target.value),
                            }))
                          }
                        />
                      </Field>
                      <StrategyParameters
                        plugin={p}
                        value={signalParameters[p.name] || "{}"}
                        onChange={(value) =>
                          setSignalParameters((v) => ({
                            ...v,
                            [p.name]: value,
                          }))
                        }
                      />
                      <p className="mt-1">
                        预热至少 {p.min_history} 根；
                        {p.dependency
                          ? `依赖 ${p.dependency.strategy_name}，回看 ${p.dependency.days_ago} 根`
                          : "无前置信号依赖"}
                      </p>
                      <p>参数改变后，实际预热要求以数据检查为准。</p>
                    </details>
                  )}
                  <StrategyLearning plugin={p} />
                </div>
              ))}
          </fieldset>
          <div className="grid grid-cols-2 gap-3">
            <Field title="组合条件">
              <select
                className={input}
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="all">全部命中</option>
                <option value="any">任一命中</option>
                <option value="at_least">至少 N 个</option>
              </select>
            </Field>
            {mode === "at_least" && (
              <Field title="最少命中数">
                <input
                  className={input}
                  type="number"
                  min={1}
                  max={selected.length}
                  value={minimum}
                  onChange={(e) => setMinimum(Number(e.target.value))}
                />
              </Field>
            )}
          </div>
        </>
      )}
      <Field title="交易策略插件">
        <select
          className={input}
          value={portfolio}
          onChange={(e) => {
            setPortfolio(e.target.value);
            setParameterText("{}");
            setSignalExit(false);
          }}
        >
          {plugins
            .filter((p) => p.kind === "portfolio")
            .map((p) => (
              <option key={p.name} value={p.name} disabled={!p.enabled}>
                {p.title}
                {!p.enabled ? "（已禁用）" : ""}
              </option>
            ))}
        </select>
      </Field>
      {portfolioInfo && (
        <>
          <StrategyParameters
            plugin={portfolioInfo}
            value={parameterText}
            onChange={setParameterText}
          />
          <StrategyLearning plugin={portfolioInfo} />
        </>
      )}
      {!usesSignals && (
        <p className="rounded-lg bg-blue-50 p-3 text-xs leading-6 text-blue-900">
          此交易策略自行决定选股、调仓和退出，不叠加信号组合。通用费用、仓位上限和额外退出规则仍然生效。
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field title="初始资金">{number(cash, setCash, "0.01")}</Field>
        <Field title="最多持仓数">
          <input
            className={input}
            type="number"
            min={1}
            max={500}
            value={maxPositions}
            onChange={(e) => setMaxPositions(Number(e.target.value))}
          />
        </Field>
        <Field title="单股目标权重上限（0–1）">
          {number(weight, setWeight, "0.001", "1")}
        </Field>
        <Field title="可投资比例（0–1）">
          {number(fraction, setFraction, "0.001", "1")}
        </Field>
        {usesSignals && (
          <Field title="候选排序">
            <select
              className={input}
              value={rank}
              onChange={(e) => setRank(e.target.value)}
            >
              <option value="hits">命中数，代码破同分</option>
              <option value="momentum">20 日动量，缺失不排名</option>
              <option value="symbol">代码顺序</option>
            </select>
          </Field>
        )}
        <Field title="选股调度">
          <select
            className={input}
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
          >
            <option value="daily">每日收盘</option>
            <option value="weekly">每周首个观察日收盘</option>
            <option value="monthly">每月首个观察日收盘</option>
          </select>
        </Field>
      </div>
      {usesSignals && (
        <label className="flex gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={rebalance}
            onChange={(e) => setRebalance(e.target.checked)}
          />
          按调度重新排名调仓（关闭则保留持仓，按退出规则卖出）
        </label>
      )}
      <details className="space-y-3" open>
        <summary className="cursor-pointer text-sm font-medium">
          退出与执行模型
        </summary>
        <p className="text-xs leading-5 text-slate-500">
          以下为可编辑的研究假设，请按实验填写；费率不代表当前券商或税费标准。退出由收盘触发，次日开盘尝试成交。
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[
            ["止损比例（留空关闭）", stop, setStop],
            ["止盈比例（留空关闭）", profit, setProfit],
            ["跟踪退出比例（留空关闭）", trailing, setTrailing],
            ["最长持有观察日（留空关闭）", days, setDays],
          ].map(([label, value, setter]) => (
            <Field key={String(label)} title={String(label)}>
              <input
                className={input}
                type="number"
                step="any"
                min="0"
                value={value as string}
                onChange={(e) =>
                  (setter as (v: string) => void)(e.target.value)
                }
              />
            </Field>
          ))}
          <Field title="佣金比例">{number(commission, setCommission)}</Field>
          <Field title="最低佣金">
            {number(minCommission, setMinCommission)}
          </Field>
          <Field title="卖出税费比例">{number(tax, setTax)}</Field>
          <Field title="单边滑点（基点，1 = 0.01%）">
            {number(slippage, setSlippage)}
          </Field>
          <Field title="每手数量">
            <input
              className={input}
              type="number"
              min={1}
              value={lot}
              onChange={(e) => setLot(Number(e.target.value))}
            />
          </Field>
          <Field title="卖出结算等待观察日">
            <input
              className={input}
              type="number"
              min={0}
              max={10}
              value={settlement}
              onChange={(e) => setSettlement(Number(e.target.value))}
            />
          </Field>
          <Field title="每次成交/前日成交量上限">
            {number(volume, setVolume, "0.0001", "1")}
          </Field>
          <Field title="开盘涨跌幅限制（留空不检查）">
            <input
              className={input}
              type="number"
              step="any"
              min="0"
              max="1"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </Field>
        </div>
        {usesSignals && (
          <label className="flex gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={signalExit}
              onChange={(e) => setSignalExit(e.target.checked)}
            />
            启用基础策略的退出信号
          </label>
        )}
      </details>
      <Field title="股票池缺日处理">
        <select
          className={input}
          value={missing}
          onChange={(e) => setMissing(e.target.value)}
        >
          <option value="error">拒绝运行，先补数据</option>
          <option value="skip_with_warning">显式跳过并在报告标记</option>
        </select>
      </Field>
      <label className="flex gap-2 rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-900">
        <input
          type="checkbox"
          className="mt-1 shrink-0"
          checked={accepted}
          onChange={(e) => setAccepted(e.target.checked)}
          required
        />
        <span>
          确认使用
          {adjustment === "none"
            ? "原始价模型（不含分红拆股处理）"
            : "复权价格研究模型（模拟份额不等同历史原始成交）"}
          ；固定股票池与成交假设会写入报告。
        </span>
      </label>
      {preflight && (
        <div
          role="status"
          className="rounded-lg bg-blue-50 p-3 text-xs leading-6 text-blue-900"
        >
          数据检查完成：{preflight.calendar.length} 个观察日，
          {preflight.series.length} 个序列。
          {preflight.warnings.map((w) => (
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
          type="button"
          className={button}
          disabled={busy || !source}
          onClick={(e) => void submit(e, true)}
        >
          检查数据
        </button>
        <button
          className={button + " !border-blue-600 !bg-blue-600 !text-white"}
          disabled={busy || !source || !accepted}
        >
          <Play size={15} />
          {busy ? "处理中…" : "开始回测"}
        </button>
      </div>
    </form>
  );
}

function Report({ experiment }: { experiment: Experiment }) {
  const [tab, setTab] = useState("trades");
  const [page, setPage] = useState(0);
  const [holdDate, setHoldDate] = useState("");
  const report = experiment.report;
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
        {experiment.status === "stale" && (
          <p className="mt-3 text-sm text-amber-700">
            任务中断，冻结输入保留。请通过 CLI 检查后重新创建实验。
          </p>
        )}
        <ol className="mt-4 space-y-2 text-sm text-slate-600">
          {experiment.events.map((event, i) => (
            <li key={i}>{event.message}</li>
          ))}
        </ol>
      </section>
    );
  const metrics = report.metrics;
  const trades = report.trades.slice(page * 50, page * 50 + 50);
  const orders = report.orders.slice(page * 50, page * 50 + 50);
  const holdings =
    report.curve.find((p) => p.date === holdDate)?.holdings || report.positions;
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(experiment, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `backtest-${experiment.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  const cell = "whitespace-nowrap px-3 py-3 text-left text-xs";
  return (
    <div className="space-y-5">
      <section className={panel}>
        <div className="flex flex-wrap justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{experiment.name}</h2>
            <p className="mt-1 text-xs text-slate-500">
              {experiment.config.start} — {experiment.config.end} ·{" "}
              {experiment.config.source} / {experiment.config.adjustment} ·{" "}
              {experiment.config.currency} · {experiment.config.symbols.length}{" "}
              只股票
            </p>
          </div>
          <button className={button} onClick={download}>
            <Download size={15} />
            导出报告 JSON
          </button>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-4 xl:grid-cols-3">
          {[
            ["累计收益", percent(metrics.total_return)],
            ["最大回撤", percent(metrics.max_drawdown)],
            [
              "期末权益",
              `${money(metrics.final_equity)} ${experiment.config.currency}`,
            ],
            [
              "交易次数 / 费用",
              `${metrics.trade_count} / ${money(metrics.fees)} ${experiment.config.currency}`,
            ],
            [
              "换手 / 最大仓位",
              `${percent(metrics.turnover)} / ${percent(metrics.max_exposure)}`,
            ],
            [
              "基准 / 超额收益",
              `${percent(metrics.benchmark_return)} / ${percent(metrics.excess_return)}`,
            ],
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-slate-500">
          年化收益 {percent(metrics.annualized_return)} · 夏普（无风险利率 0）
          {metrics.sharpe_zero_rf == null
            ? "未知"
            : metrics.sharpe_zero_rf.toFixed(2)}{" "}
          · 卖出成交盈利比例 {percent(metrics.sell_fill_win_rate)} ·{" "}
          {metrics.observed_days} 个观察日
        </p>
      </section>
      <section className={panel}>
        <h3 className="mb-4 font-semibold">
          组合净值与基准 · {experiment.config.currency}
        </h3>
        <Chart points={report.curve} />
        <h3 className="mb-3 mt-5 text-sm font-medium">回撤</h3>
        <Chart points={report.curve} drawdown />
      </section>
      <section className={panel + " border-amber-200 bg-amber-50/40"}>
        <h3 className="mb-2 text-sm font-semibold">数据与模型限制</h3>
        <ul className="list-disc space-y-1 pl-4 text-xs leading-6 text-slate-600">
          {report.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </section>
      <section className={panel}>
        <div
          role="tablist"
          aria-label="报告明细"
          className="mb-4 flex flex-wrap gap-2"
        >
          {[
            ["trades", "成交"],
            ["orders", "订单与未成交原因"],
            ["holdings", "持仓"],
            ["inputs", "配置与数据清单"],
          ].map(([key, label]) => (
            <button
              role="tab"
              aria-selected={tab === key}
              key={key}
              className={
                button +
                (tab === key
                  ? " !border-blue-300 !bg-blue-50 !text-blue-700"
                  : "")
              }
              onClick={() => {
                setTab(key);
                setPage(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "trades" && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  {[
                    "成交日期",
                    "信号日期",
                    "股票",
                    "方向",
                    "数量",
                    "价格",
                    "费用",
                    "已实现盈亏",
                    "原因",
                  ].map((t) => (
                    <th className={cell} key={t}>
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.order_id} className="border-b border-slate-100">
                    {[
                      t.date,
                      t.signal_date,
                      t.symbol,
                      t.side === "buy" ? "买入" : "卖出",
                      t.quantity,
                      money(t.price),
                      money(t.fee),
                      money(t.realized_pnl),
                      reasonLabel[t.reason] || t.reason,
                    ].map((value, i) => (
                      <td className={cell} key={i}>
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!report.trades.length && (
              <p className="py-8 text-center text-sm text-slate-500">
                区间内没有成交。请查看订单与信号证据缺口。
              </p>
            )}
          </div>
        )}
        {tab === "orders" && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50">
                <tr>
                  {[
                    "信号日期",
                    "执行日期",
                    "股票",
                    "目标权重",
                    "状态",
                    "成交数量",
                    "信号依据",
                    "原因",
                  ].map((t) => (
                    <th className={cell} key={t}>
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id} className="border-b border-slate-100">
                    {[
                      o.signal_date,
                      o.execution_date || "—",
                      o.symbol,
                      percent(o.target_weight),
                      statusLabel[o.status] || o.status,
                      o.filled_quantity || 0,
                      Object.entries(o.signal_evidence || {})
                        .map(
                          ([name, evidence]) =>
                            `${experiment.plugins.find((p) => p.name === name)?.title || name}：${evidence.hit == null ? "未知" : evidence.hit ? "命中" : "未命中"}（${evidence.lookback} 日）`,
                        )
                        .join("；") ||
                        reasonLabel[o.decision_evidence?.summary || ""] ||
                        o.decision_evidence?.summary ||
                        "—",
                      reasonLabel[o.execution_reason || ""] ||
                        o.execution_reason ||
                        reasonLabel[o.reason] ||
                        o.reason,
                    ].map((value, i) => (
                      <td className={cell} key={i}>
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!report.orders.length && (
              <p className="py-8 text-center text-sm text-slate-500">
                没有委托。组合可能未命中或缺少足够证据。
              </p>
            )}
          </div>
        )}
        {(tab === "trades" || tab === "orders") && (
          <div className="mt-4 flex items-center justify-end gap-3 text-xs text-slate-500">
            <button
              className={button}
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              上一页
            </button>
            <span>第 {page + 1} 页</span>
            <button
              className={button}
              disabled={
                (page + 1) * 50 >=
                (tab === "trades" ? report.trades.length : report.orders.length)
              }
              onClick={() => setPage((p) => p + 1)}
            >
              下一页
            </button>
          </div>
        )}
        {tab === "holdings" && (
          <div>
            <Field title="观察日期">
              <select
                className={input + " mb-4 max-w-xs"}
                value={holdDate || report.curve[report.curve.length - 1].date}
                onChange={(e) => setHoldDate(e.target.value)}
              >
                {report.curve.map((p) => (
                  <option key={p.date}>{p.date}</option>
                ))}
              </select>
            </Field>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50">
                  <tr>
                    {[
                      "股票",
                      "数量",
                      "含买入费用成本",
                      "估值价格",
                      "市值",
                      "浮动盈亏",
                      "估值状态",
                    ].map((t) => (
                      <th className={cell} key={t}>
                        {t}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h) => (
                    <tr key={h.symbol}>
                      {[
                        h.symbol,
                        h.quantity,
                        money(h.average_cost),
                        money(h.price),
                        money(h.value),
                        money(h.unrealized_pnl),
                        h.stale ? "缺行情，沿用旧估值" : "当日收盘",
                      ].map((v, i) => (
                        <td className={cell} key={i}>
                          {v}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {!holdings.length && (
                <p className="py-5 text-sm text-slate-500">当日无持仓</p>
              )}
            </div>
          </div>
        )}
        {tab === "inputs" && (
          <div className="space-y-4 text-xs text-slate-600">
            <p className="break-all">
              输入 SHA-256：{experiment.manifest.input_hash}
              <br />
              结果 SHA-256：{report.result_hash}
              <br />
              内核版本：{experiment.engine_version}
            </p>
            <p>
              插件：
              {experiment.plugins
                .map((p) => `${p.name}@${p.version} (${p.hash.slice(0, 12)})`)
                .join("，")}
            </p>
            <details open>
              <summary>策略学习说明（随实验归档）</summary>
              {experiment.plugins.map((plugin) => (
                <div
                  className="my-3 rounded-lg border border-slate-200 p-3"
                  key={plugin.name}
                >
                  <p className="font-semibold">{plugin.title || plugin.name}</p>
                  <StrategyLearning
                    plugin={plugin}
                    parameters={
                      plugin.kind === "portfolio"
                        ? experiment.config.strategy_parameters
                        : experiment.config.combination?.signals.find(
                            (spec) => spec.name === plugin.name,
                          )?.parameters
                    }
                  />
                </div>
              ))}
            </details>
            <details open>
              <summary>实验配置</summary>
              <pre className="mt-2 max-h-96 overflow-auto rounded bg-slate-50 p-3">
                {JSON.stringify(experiment.config, null, 2)}
              </pre>
            </details>
            <details>
              <summary>数据清单、预热与缺口</summary>
              <pre className="mt-2 max-h-96 overflow-auto rounded bg-slate-50 p-3">
                {JSON.stringify(experiment.manifest, null, 2)}
              </pre>
            </details>
            <details>
              <summary>执行假设</summary>
              <pre className="mt-2 overflow-auto rounded bg-slate-50 p-3">
                {JSON.stringify(report.assumptions, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </section>
    </div>
  );
}

export default function BacktestsPage({ id }: { id?: string }) {
  const { market, source, adjustment } = useMarket();
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [managerOpen, setManagerOpen] = useState(
    () => new URLSearchParams(location.search).get("learn") === "1",
  );
  const [strategySearch, setStrategySearch] = useState("");
  const [choice, setChoice] = useState<{
    plugin: Plugin;
    sequence: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [toggling, setToggling] = useState("");
  const scopeKey = `${market}:${source}:${adjustment}`;
  useEffect(() => {
    let cancelled = false;
    setRows([]);
    setExperiment(null);
    setError("");
    setLoading(true);
    Promise.all([loadExperiments(), loadPlugins()])
      .then(([rows, plugins]) => {
        if (!cancelled) {
          setRows(rows);
          setPlugins(plugins);
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
  }, [scopeKey, refresh]);
  useEffect(() => {
    if (!id) {
      setExperiment(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setExperiment(null);
    const poll = () =>
      loadExperiment(id)
        .then((data) => {
          if (cancelled) return;
          setExperiment(data);
          setRows((rows) =>
            rows.map((row) =>
              row.id === data.id
                ? {
                    ...row,
                    status: data.status,
                    metrics: data.report?.metrics || null,
                  }
                : row,
            ),
          );
          if (["queued", "running"].includes(data.status))
            timer = setTimeout(poll, 1500);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, scopeKey, refresh]);
  async function toggle(plugin: Plugin) {
    setToggling(plugin.name);
    setError("");
    try {
      await mutate(
        `/api/backtests/plugins/${encodeURIComponent(plugin.name)}`,
        { enabled: !plugin.enabled },
        "PATCH",
      );
      setPlugins(await loadPlugins());
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败");
    } finally {
      setToggling("");
    }
  }
  return (
    <SelectionShell currentSection="backtests">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">策略与回测</h1>
          <p className="mt-1 text-sm text-slate-500">
            多股票共享资金 · 冻结输入 · 本地离线回放
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className={button}
            onClick={() => setRefresh((v) => v + 1)}
            aria-label="刷新回测列表"
          >
            <RefreshCw size={15} />
          </button>
          <button className={button} onClick={() => setManagerOpen((v) => !v)}>
            <Settings2 size={15} />
            策略管理
          </button>
          <button className={button} onClick={() => setNewOpen((v) => !v)}>
            <Plus size={15} />
            {newOpen ? "收起配置" : "新建回测"}
          </button>
        </div>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg bg-red-50 p-4 text-sm text-red-700"
        >
          {error}{" "}
          <button
            className="ml-3 underline"
            onClick={() => setRefresh((v) => v + 1)}
          >
            重试
          </button>
        </div>
      )}
      {!source && (
        <p className={panel + " text-sm text-amber-700"}>
          当前市场没有可用行情来源，请先通过 CLI 导入所需范围的日线。
        </p>
      )}
      {managerOpen && (
        <section className={panel}>
          <h2 className="mb-2 font-semibold">
            策略库与学习 · {plugins.filter((p) => p.kind === "signal").length}{" "}
            个信号 / {plugins.filter((p) => p.kind === "portfolio").length}{" "}
            个交易策略
          </h2>
          <p className="mb-4 text-xs text-slate-500">
            先理解假设与条件，再编辑参数并回测。所有默认值都是研究示例，启停只影响新实验；说明不代替个人纪律规则。
          </p>
          <label className="mb-4 block max-w-lg text-xs text-slate-600">
            搜索策略或类别
            <input
              aria-label="搜索策略或类别"
              className={input + " mt-1"}
              value={strategySearch}
              onChange={(e) => setStrategySearch(e.target.value)}
              placeholder="例如：均值回归、动量、海龟"
            />
          </label>
          <details className="mb-4 rounded-lg bg-slate-50 p-3 text-xs leading-6 text-slate-600">
            <summary className="cursor-pointer font-medium">
              术语速查：信号、组合、预热、ATR 与观察交易日
            </summary>
            <p>
              信号回答单只股票是否满足条件；交易策略还决定买谁、买多少及何时调仓。预热是计算指标前所需的历史，不计入实验收益。观察交易日来自缓存日期，不是自然日，也不保证交易所日历完整。ATR
              描述真实波幅；按 ATR
              估算的计划风险仍受跳空和成交影响。已知未命中与证据未知会分别处理。
            </p>
          </details>
          <div className="grid items-start gap-3 md:grid-cols-2">
            {plugins
              .filter((p) =>
                `${p.title} ${p.name} ${p.education?.family || ""}`
                  .toLowerCase()
                  .includes(strategySearch.trim().toLowerCase()),
              )
              .map((p) => (
                <div
                  key={p.name}
                  className="rounded-lg border border-slate-200 p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{p.title}</p>
                      <p className="mt-1 break-all text-xs text-slate-500">
                        {p.name} · {p.kind === "signal" ? "信号" : "交易策略"} ·
                        v{p.version}
                      </p>
                    </div>
                    <button
                      disabled={!!toggling}
                      className={button}
                      onClick={() => void toggle(p)}
                    >
                      {p.enabled ? "禁用" : "启用"}
                    </button>
                  </div>
                  <p className="mt-3 text-xs font-medium text-blue-700">
                    {p.education?.family || "外部插件"} · 日线 · 只做多
                  </p>
                  <p className="mt-1 text-sm leading-6 text-slate-600">
                    {p.education?.summary || "请阅读插件说明。"}
                  </p>
                  <StrategyLearning plugin={p} />
                  <button
                    disabled={!p.enabled}
                    className={button + " mt-4"}
                    onClick={() => {
                      setChoice({ plugin: p, sequence: Date.now() });
                      setNewOpen(true);
                    }}
                  >
                    {p.kind === "signal" ? "用此信号回测" : "用此交易策略回测"}
                  </button>
                </div>
              ))}
          </div>
        </section>
      )}
      <section className={panel}>
        <h2 className="mb-3 font-semibold">
          实验记录 · {market} / {source || "无来源"} / {adjustment}
        </h2>
        {loading ? (
          <p role="status" className="py-5 text-sm text-slate-500">
            正在读取实验…
          </p>
        ) : !rows.length ? (
          <p className="py-5 text-sm text-slate-500">
            还没有此范围的回测。点击“新建回测”，选择策略组合和股票池。
          </p>
        ) : (
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  {[
                    "实验",
                    "区间 / 股票数",
                    "状态",
                    "累计收益",
                    "最大回撤",
                  ].map((t) => (
                    <th className="px-3 py-2" key={t}>
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className={
                      id === row.id ? "bg-blue-50" : "border-b border-slate-100"
                    }
                  >
                    <td className="px-3 py-3">
                      <button
                        className="text-left font-medium text-blue-700 hover:underline"
                        onClick={() =>
                          openPath(scopedPath(`/backtests/${row.id}`))
                        }
                      >
                        {row.name}
                      </button>
                    </td>
                    <td className="px-3 py-3">
                      {row.config.start} — {row.config.end} /{" "}
                      {row.config.symbols.length} 只
                    </td>
                    <td className="px-3 py-3">
                      {statusLabel[row.status] || row.status}
                    </td>
                    <td className="px-3 py-3">
                      {percent(row.metrics?.total_return)}
                    </td>
                    <td className="px-3 py-3">
                      {percent(row.metrics?.max_drawdown)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <div
        className={
          newOpen
            ? "grid items-start gap-5 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]"
            : ""
        }
      >
        {newOpen && (
          <ExperimentForm
            key={scopeKey}
            plugins={plugins}
            choice={choice}
            onStarted={(newId) => {
              setRefresh((v) => v + 1);
              openPath(scopedPath(`/backtests/${newId}`));
            }}
          />
        )}
        <div className="min-w-0">
          {experiment ? (
            <Report key={experiment.id} experiment={experiment} />
          ) : (
            <div
              className={panel + " py-16 text-center text-sm text-slate-500"}
            >
              {id && !error
                ? "正在读取报告…"
                : "选择一份实验报告，查看组合净值、订单和数据依据。"}
            </div>
          )}
        </div>
      </div>
    </SelectionShell>
  );
}
