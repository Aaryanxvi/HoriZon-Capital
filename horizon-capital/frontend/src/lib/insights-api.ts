import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

// Read-only analysis tabs — backend/app/api/desktop_insights.py.
const BASE = "/api/desktop/insights";

// ponytail: same local `get` as viz-api.ts; fold into an exported api.ts `get` when one exists.
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

/** A statistic with its sample size; `value` is null below `min`. */
export interface Gated {
  value: number | null;
  n: number;
  min: number;
}

export interface RiskPosition {
  symbol: string;
  market_value: number;
  weight: number | null;
  price: number;
  stop: number | null;
  stop_distance_pct: number | null;
  loss_at_stop: number | null;
  bars: number;
  last_bar: string | null;
  vol: number | null;
  beta: number | null;
  risk_share: number | null;
  adv_usd: number | null;
  days_to_exit: number | null;
}

export interface Scenario {
  key: string;
  label: string;
  pnl: number | null;
  unmodeled_usd: number;
  date?: string | null;
}

export interface RiskInsights {
  nav: number;
  cash: number;
  cash_pct: number | null;
  gross: number;
  positions: RiskPosition[];
  port_vol: Gated;
  risk_covered_usd: number;
  book_beta: { value: number | null; covered_usd: number; min: number };
  scenarios: Scenario[];
  replay_days: number;
  replay_from: string | null;
  stops: { loss_if_all_hit: number; unprotected_count: number; unprotected_usd: number };
  concentration: {
    top1: number | null;
    top5: number | null;
    hhi: number | null;
    effective_n: number | null;
    count: number;
  };
  assumptions: { lookback_days: number; min_bars: number; participation: number; adv_days: number };
}

export interface ClosedTrade {
  symbol: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  entry_at: string;
  exit_at: string;
  pnl: number;
  return_pct: number | null;
  holding_days: number | null;
  mae_pct: number | null;
  mfe_pct: number | null;
}

export interface TradesInsights {
  closed: ClosedTrade[];
  stats: {
    count: number;
    win_rate: Gated;
    avg_win: Gated;
    avg_loss: Gated;
    expectancy: Gated;
    profit_factor: Gated;
    max_win_streak: Gated;
    max_loss_streak: Gated;
    total_pnl: number;
  };
  unmatched_exits: { symbol: string; qty: number; price: number; filled_at: string }[];
  turnover: { month: string; notional: number; fills: number; avg_nav: number | null; turnover: number | null }[];
  open: {
    symbol: string;
    qty: number;
    short: boolean;
    entry_price: number;
    price: number;
    market_value: number;
    unrealized_pnl: number;
    realized_pnl: number;
    age_days: number | null;
  }[];
  min_trades: number;
}

export interface BenchmarkInsights {
  symbol: string;
  nav_days: number;
  days: number;
  window: [string, string] | null;
  min_days: number;
  min_capture_days: number;
  beta: Gated;
  alpha: Gated;
  correlation: Gated;
  tracking_error: Gated;
  information_ratio: Gated;
  up_capture: Gated;
  down_capture: Gated;
  portfolio_return: Gated;
  benchmark_return: Gated;
  excess_return: Gated;
}

export interface CostRow {
  key: string;
  calls: number;
  cost: number;
  tokens: number;
}

export interface CostsInsights {
  fills: {
    count: number;
    notional: number;
    commission: number;
    slippage: number;
    slippage_unmeasured: number;
  };
  llm:
    | { recorded: false }
    | {
        recorded: true;
        calls: number;
        cost: number;
        input_tokens: number;
        output_tokens: number;
        estimated_calls: number;
        first: string;
        last: string;
        by_day: CostRow[];
        by_agent: CostRow[];
        by_model: CostRow[];
        by_purpose: CostRow[];
        per_debate: { value: number | null; n: number };
        per_filled_order: { value: number | null; n: number };
      };
}

export interface Feed {
  name: string;
  last: string | null;
  age_s: number | null;
  stale_after_s: number;
}

export interface HealthInsights {
  now: string;
  engine: { running: boolean; mode: string; halted: boolean; kill_switch: boolean };
  feeds: Feed[];
  symbols: {
    symbol: string;
    held: boolean;
    last_daily: string | null;
    last_intraday: string | null;
    daily_age_s: number | null;
    intraday_age_s: number | null;
  }[];
  llm: {
    configured: string[];
    failures: { provider: string | null; error: string | null; message: string; at: string; acknowledged: boolean }[];
    last_logged_call: Record<string, string>;
  };
  agents: {
    agent_id: string;
    status: string;
    restarts: number | null;
    last_heartbeat: string | null;
    age_s: number | null;
    error?: string | null;
  }[];
  workers: { name: string; status: string; restarts: number }[];
  agents_live: boolean;
  unacked_alerts: Record<string, { count: number; last: string }>;
}

const opts = { staleTime: 60_000, refetchInterval: 120_000 };

export const useRiskInsights = () =>
  useQuery({ queryKey: ["insights", "risk"], queryFn: () => get<RiskInsights>("/risk"), ...opts });
export const useTradesInsights = () =>
  useQuery({ queryKey: ["insights", "trades"], queryFn: () => get<TradesInsights>("/trades"), ...opts });
export const useBenchmarkInsights = () =>
  useQuery({ queryKey: ["insights", "benchmark"], queryFn: () => get<BenchmarkInsights>("/benchmark"), ...opts });
export const useCostsInsights = () =>
  useQuery({ queryKey: ["insights", "costs"], queryFn: () => get<CostsInsights>("/costs"), ...opts });
export const useHealthInsights = () =>
  useQuery({
    queryKey: ["insights", "health"],
    queryFn: () => get<HealthInsights>("/health"),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
