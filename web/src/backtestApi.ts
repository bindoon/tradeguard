import { apiFetch } from "./api";

export type Plugin = {
  uses_signals?: boolean;
  default_parameters?: Record<string, unknown>;
  education?: StrategyEducation;
  name: string;
  title: string;
  kind: "signal" | "portfolio";
  enabled: boolean;
  version: string;
  hash: string;
  min_history: number;
  frequency: string;
  dependency: { strategy_name: string; days_ago: number } | null;
  parameters_schema: Record<string, unknown>;
};
export type StrategyEducation = {
  suitable_for?: string[];
  schema_version: number;
  family: string;
  summary: string;
  idea: string;
  entry: string[];
  exit: string[];
  sizing: string;
  data: string[];
  example: string;
  pitfalls: string[];
  variant: string;
  sources: { title: string; url?: string }[];
  fixed_parameters: string[];
};
export type Metrics = {
  initial_cash: string;
  final_equity: string;
  total_return: string;
  max_drawdown: string;
  annualized_return: number | null;
  sharpe_zero_rf: number | null;
  turnover: string | null;
  fees: string;
  trade_count: number;
  sell_fill_win_rate: string | null;
  max_exposure: string;
  observed_days: number;
  benchmark_return: string | null;
  excess_return: string | null;
};
export type Holding = {
  symbol: string;
  quantity: number;
  average_cost: string;
  price: string;
  value: string;
  unrealized_pnl: string;
  stale: boolean;
};
export type CurvePoint = {
  date: string;
  cash: string;
  market_value: string;
  equity: string;
  drawdown: string;
  exposure: string;
  benchmark_equity: string | null;
  holdings: Holding[];
};
export type Order = {
  decision_evidence?: { summary?: string; [key: string]: unknown } | null;
  signal_evidence?: Record<string, { hit: boolean | null; lookback: number }>;
  id: number;
  symbol: string;
  signal_date: string;
  target_weight: string;
  reason: string;
  status: string;
  execution_date: string | null;
  execution_reason: string | null;
  requested_quantity?: number;
  filled_quantity?: number;
};
export type Trade = {
  order_id: number;
  symbol: string;
  side: string;
  signal_date: string;
  date: string;
  quantity: number;
  price: string;
  notional: string;
  fee: string;
  realized_pnl: string | null;
  reason: string;
};
export type Config = {
  name: string;
  market: string;
  currency: string;
  source: string;
  adjustment: string;
  price_model: string;
  frequency: "1d";
  start: string;
  end: string;
  symbols: string[];
  benchmark: string | null;
  initial_cash: string;
  combination: null | {
    mode: string;
    minimum: number;
    signals: {
      name: string;
      parameters: Record<string, unknown>;
      lookback: number;
    }[];
  };
  portfolio_strategy: string;
  strategy_parameters: Record<string, unknown>;
  max_positions: number;
  max_weight: string;
  invested_fraction: string;
  rank_by: string;
  schedule: string;
  rebalance: boolean;
  missing_data: string;
  execution: {
    commission: string;
    minimum_commission: string;
    sell_tax: string;
    slippage_bps: string;
    lot_size: number;
    settlement_days: number;
    limit_pct: string | null;
    prior_volume_fraction: string;
  };
  exits: {
    stop_loss: string | null;
    take_profit: string | null;
    trailing_stop: string | null;
    max_holding_days: number | null;
    signal_exit: boolean;
  };
};
export type Manifest = {
  input_hash: string;
  calendar: string[];
  warnings: string[];
  series: { symbol: string; rows: number; hash: string }[];
  gaps: { symbol: string; missing: string[] }[];
  warmup: { symbol: string; observed: number; required: number }[];
};
export type Experiment = {
  id: string;
  name: string;
  status: string;
  market: string;
  created_at: string;
  config: Config;
  manifest: Manifest;
  plugins: Plugin[];
  engine_version: string;
  replay_of: string | null;
  error?: string;
  events: {
    stage: string;
    message: string;
    completed: number | null;
    total: number | null;
  }[];
  report: null | {
    metrics: Metrics;
    curve: CurvePoint[];
    orders: Order[];
    trades: Trade[];
    positions: Holding[];
    warnings: string[];
    result_hash: string;
    assumptions: Record<string, unknown>;
  };
};
export type ExperimentRow = Pick<
  Experiment,
  "id" | "name" | "status" | "created_at" | "config" | "error"
> & { metrics: Metrics | null };

const base = (import.meta.env.VITE_API_URL as string) || "";
export async function mutate<T>(
  path: string,
  body: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) {
    const message =
      typeof value.detail === "string"
        ? value.detail
        : Array.isArray(value.detail)
          ? value.detail
              .map(
                (item: { loc: string[]; msg: string }) =>
                  `${item.loc.join(".")}: ${item.msg}`,
              )
              .join("；")
          : "请求失败，请稍后重试";
    throw new Error(message);
  }
  return value;
}
export const loadPlugins = () => apiFetch<Plugin[]>("/api/backtests/plugins");
export const loadExperiments = () =>
  apiFetch<ExperimentRow[]>("/api/backtests");
export const loadExperiment = (id: string) =>
  apiFetch<Experiment>(`/api/backtests/${encodeURIComponent(id)}`);

export function percent(value: string | number | null | undefined): string {
  return value == null ? "未知" : `${(Number(value) * 100).toFixed(2)}%`;
}
export function money(value: string | null | undefined): string {
  return value == null
    ? "未知"
    : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

export const statusLabel: Record<string, string> = {
  success: "已完成",
  queued: "排队中",
  running: "回放中",
  failed: "失败",
  stale: "已中断",
  filled: "已成交",
  partial: "部分成交",
  rejected: "未成交",
  cancelled: "已取消",
  expired: "已到期",
};
export const reasonLabel: Record<string, string> = {
  insufficient_fee_cash: "卖出所得与现金不足以支付费用",
  portfolio_target: "组合目标仓位",
  missing_bar: "缺少当日行情",
  suspended_or_invalid_price: "停牌或价格无效",
  missing_prior_liquidity: "缺少前日流动性",
  configured_limit_move: "达到配置的涨跌幅限制",
  prior_volume_cap: "前日成交量比例限制",
  insufficient_cash: "可用现金不足",
  settlement_wait: "未达到结算等待期",
  max_positions: "持仓数达到上限",
  already_at_target: "已达到目标仓位",
  end_of_test: "区间结束，无后续成交日",
  stop_loss_at_close: "收盘触发止损",
  take_profit_at_close: "收盘触发止盈",
  trailing_stop_at_close: "收盘触发跟踪退出",
  max_holding_days: "达到持有期限",
  filled: "按模型成交",
};
