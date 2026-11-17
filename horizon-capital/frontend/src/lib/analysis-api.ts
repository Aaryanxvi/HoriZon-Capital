import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

// "What is making or losing money, and why" — backend/app/api/desktop_analysis.py.
const BASE = "/api/desktop/analysis";

// ponytail: same local `get` as viz-api.ts; fold into an exported one from api.ts later.
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

/** An aggregate with its sample size; `value` is null below `min`. */
export interface Sampled {
  value: number | null;
  n: number;
  min: number;
}

export interface ForwardStats {
  avg: Sampled; // direction-adjusted return, fraction
  hit_rate: Sampled; // fraction of samples > 0
}
export type Horizon = "1d" | "5d" | "20d";
export const HORIZONS: Horizon[] = ["1d", "5d", "20d"];

export type AssetClass = "equity" | "etf" | "crypto" | "prediction";

export interface PnlRow {
  symbol: string;
  asset_class: AssetClass;
  sleeve: string;
  open: boolean;
  realized: number;
  unrealized: number;
  total: number;
  contribution: number | null; // fraction of base NAV
}

export interface PnlResponse {
  base_nav: number | null;
  base_at: string | null;
  nav: number | null;
  nav_change: number | null;
  explained: number;
  unexplained: number | null;
  positions: PnlRow[];
  sleeves: { sleeve: string; realized: number; unrealized: number; total: number; positions: number; contribution: number | null }[];
  attribution: "asset_class";
}

export interface Holding {
  symbol: string;
  asset_class: AssetClass;
  sector: string | null;
  value: number;
  weight: number | null;
  beta: Sampled;
}

export interface ExposureResponse {
  nav: number | null;
  gross: number;
  net: number;
  by_asset_class: { name: string; value: number }[];
  by_sector: { name: string; value: number }[];
  holdings: Holding[];
  book_beta: Sampled;
  correlation: { symbols: string[]; matrix: (number | null)[][]; n: number[][]; min: number };
}

export interface VoteCounts {
  name: string;
  for: number;
  against: number;
  abstain: number;
  error: number;
}

export interface DebateRow {
  id: string;
  symbol: string;
  action: string;
  decision: string;
  created_at: string;
  fwd_1d: number | null;
  fwd_5d: number | null;
  fwd_20d: number | null;
}

export interface DebatesResponse {
  total: number;
  approval_rate: Sampled;
  by_day: { date: string; approved: number; rejected: number; other: number; rate: Sampled }[];
  by_role: VoteCounts[];
  by_provider: VoteCounts[];
  round2_flips: Sampled & { flips: number };
  outcome: Record<string, Record<Horizon, ForwardStats>>;
  sessions: DebateRow[];
  last_close: string | null;
}

export interface SignalsResponse {
  sleeves: ({ sleeve: string; signals: number } & Record<Horizon, ForwardStats>)[];
  attribution: "asset_class";
  last_close: string | null;
}

export interface FillRow {
  symbol: string;
  side: string;
  broker: string;
  filled_at: string;
  fill_price: number;
  arrival_price: number | null;
  arrival_bps: number | null;
  decision_price: number | null;
  decision_bps: number | null;
}

export interface ExecutionResponse {
  fills: FillRow[];
  by_broker: { broker: string; fills: number; arrival_bps: Sampled; decision_bps: Sampled }[];
  max_quote_age_s: number;
}

const opts = { staleTime: 60_000, refetchInterval: 300_000 };

export const usePnlAttribution = () =>
  useQuery({ queryKey: ["analysis", "pnl"], queryFn: () => get<PnlResponse>("/pnl"), ...opts });
export const useExposure = () =>
  useQuery({ queryKey: ["analysis", "exposure"], queryFn: () => get<ExposureResponse>("/exposure"), ...opts });
export const useDebateAnalytics = () =>
  useQuery({ queryKey: ["analysis", "debates"], queryFn: () => get<DebatesResponse>("/debates"), ...opts });
export const useSignalQuality = () =>
  useQuery({ queryKey: ["analysis", "signals"], queryFn: () => get<SignalsResponse>("/signals"), ...opts });
export const useExecutionQuality = () =>
  useQuery({ queryKey: ["analysis", "execution"], queryFn: () => get<ExecutionResponse>("/execution"), ...opts });
