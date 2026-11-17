import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get } from "@/lib/api";

// Backtest studio — backend/app/api/desktop_backtest.py. Paths are relative to /api/desktop.
const BASE = "/backtest";

export interface StrategyInfo {
  name: string;
  description: string;
}

export interface BacktestMetrics {
  total_return: number; // fractions throughout (0.12 = 12%)
  cagr: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number; // positive fraction
  win_rate: number;
  trades: number;
  round_trips: number;
}

export interface BacktestTrade {
  symbol: string;
  date: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  commission: number;
  pnl: number;
}

export interface RunSummary {
  id: string;
  status: "running" | "done" | "error";
  strategy: string;
  symbols: string[];
  start: string;
  end: string;
  capital: number;
  created_at: string;
  elapsed_s: number | null;
  error: string | null;
  metrics: BacktestMetrics | null;
  final_capital: number | null;
}

export interface RunDetail extends RunSummary {
  equity?: { date: string; value: number }[];
  benchmark?: { date: string; close: number }[];
  trades?: BacktestTrade[];
}

export interface RunRequest {
  strategy: string;
  symbols: string[];
  start: string;
  end: string;
  capital: number;
}

/** POST that keeps FastAPI's `detail` (422 validation text, 409 "still running"). */
async function postRun(body: RunRequest): Promise<{ id: string; status: string }> {
  const res = await fetch(`/api/desktop${BASE}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => null);
    const text = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg?.replace(/^Value error, /, "")).join("; ")
      : detail;
    throw new ApiError(text || `Run failed (${res.status})`, res.status);
  }
  return res.json();
}

export const useStrategies = () =>
  useQuery({
    queryKey: ["backtest", "strategies"],
    queryFn: () => get<{ strategies: StrategyInfo[]; max_symbols: number; min_date: string }>(`${BASE}/strategies`),
    staleTime: Infinity,
  });

export const useRuns = () =>
  useQuery({
    queryKey: ["backtest", "runs"],
    queryFn: () => get<{ runs: RunSummary[]; active: string | null }>(`${BASE}/runs`),
    refetchInterval: (q) => (q.state.data?.active ? 1_000 : false),
  });

export const useRun = (id: string | null) =>
  useQuery({
    queryKey: ["backtest", "run", id],
    queryFn: () => get<RunDetail>(`${BASE}/runs/${id}`),
    enabled: !!id,
    staleTime: Infinity, // finished runs never change
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1_000 : false),
  });

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postRun,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backtest", "runs"] }),
  });
}
