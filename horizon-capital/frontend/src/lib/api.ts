// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-A12B3D373865
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

// The UI is served by the backend it talks to, so relative URLs always work —
// in dev the Vite proxy forwards them to the same place.
const BASE = "/api/desktop";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Types — only the fields the UI reads
// ---------------------------------------------------------------------------

export interface Overview {
  nav: number;
  cash_usd: number;
  cash_inr: number;
  equity_value: number;
  unrealized_pnl: number;
  total_return_pct: number;
  initial_capital: number;
  day_pnl: number;
  day_pnl_pct: number;
  positions_count: number;
  system_mode: string;
  cio_mode: string;
  storage: string;
  halted: boolean;
  halt_reason: string | null;
  kill_switch: boolean;
  regime: string | null;
  agents_running: number;
  agents_total: number;
  agents_live: boolean;
  llm_providers: string[];
  performance: Record<string, number | string> | null;
  risk: Record<string, number> | null;
}

export interface Position {
  symbol: string;
  exchange: string;
  side: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  weight_pct: number;
  currency: string;
  stop_loss_price: number | null;
  updated_at: string;
  market_value: number;
  return_pct: number;
}

export interface Order {
  id: string;
  symbol: string;
  exchange: string;
  order_type: string;
  side: string;
  quantity: number;
  limit_price: number | null;
  status: string;
  broker: string;
  mode: string;
  rejection_reason: string | null;
  created_at: string;
}

export interface Fill {
  id: string;
  order_id: string;
  symbol: string | null;
  side: string | null;
  exchange: string | null;
  filled_qty: number;
  fill_price: number;
  commission: number;
  slippage: number;
  filled_at: string;
  notional: number;
}

export interface PendingOrder {
  order_id: string;
  symbol?: string;
  side?: string;
  quantity?: number;
  created_at: string;
  [key: string]: unknown;
}

export interface Signal {
  signal_id: string;
  agent_id: string;
  symbol: string;
  direction: string;
  strength: number;
  confidence: number;
  strategy_name: string | null;
  regime: string | null;
  created_at: string;
}

export interface AgentInfo {
  agent_id: string;
  status: string;
  retries: number;
  last_heartbeat: string;
  department: string;
}

export interface AgentsResponse {
  live: boolean;
  departments: {
    display_name?: string;
    department?: string;
    agents_running: number;
    agents_total: number;
    [key: string]: unknown;
  }[];
  agents: AgentInfo[];
  workers: { name: string; status: string; restarts: number }[];
}

export interface Debate {
  id: string;
  symbol: string;
  proposed_action: string | null;
  proposed_quantity: number | null;
  status: string;
  final_decision: string | null;
  consensus_score: number | null;
  total_rounds: number;
  reason: string;
  created_at: string;
}

export interface DebateArgument {
  agent_id: string;
  role: string;
  argument: string;
  vote: string;
  confidence: number;
  round_number: number;
  created_at: string;
}

export interface RiskResponse {
  latest: Record<string, number> | null;
  history: {
    var_1d_95: number;
    current_drawdown: number;
    max_drawdown: number;
    created_at: string;
  }[];
  limits: Record<string, number | null>;
  halted: boolean;
  halt_reason: string | null;
}

export interface EquityPoint {
  total_value: number;
  cash_usd: number;
  equity_value: number;
  created_at: string;
}

export interface Config {
  system_mode: string;
  cio_mode: string;
  storage_backend: string;
  initial_capital_usd: number;
  initial_capital_inr: number;
  universe: { india: string; us: string; crypto: string };
  risk: Record<string, number>;
  sleeves: {
    crypto: {
      enabled: boolean;
      weight: number;
      discovery: boolean;
      discovery_top_n: number;
    };
    polymarket: {
      enabled: boolean;
      weight: number;
      discovery: boolean;
      discovery_top_n: number;
      markets: string;
    };
  };
  llm: {
    providers: string[];
    front_office: string;
    middle_office: string;
    back_office: string;
    executive: string;
  };
  keys: Record<string, string | null>;
  version: string;
}

export interface CommandResult {
  text: string;
  html: string;
  command: string;
  error?: boolean;
  action?: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Live-ish screens poll; the websocket invalidates them the moment data moves. */
const LIVE = { refetchInterval: 15_000, staleTime: 5_000 };

export const useOverview = () =>
  useQuery({ queryKey: ["overview"], queryFn: () => get<Overview>("/overview"), ...LIVE });

export const usePositions = () =>
  useQuery({
    queryKey: ["positions"],
    queryFn: () => get<{ positions: Position[]; count: number }>("/positions"),
    ...LIVE,
  });

export const useEquityCurve = () =>
  useQuery({
    queryKey: ["equity"],
    queryFn: () => get<{ points: EquityPoint[] }>("/equity-curve?limit=800"),
    refetchInterval: 60_000,
  });

export const useOrders = () =>
  useQuery({
    queryKey: ["orders"],
    queryFn: () => get<{ orders: Order[] }>("/orders?limit=200"),
    ...LIVE,
  });

export const useFills = () =>
  useQuery({
    queryKey: ["fills"],
    queryFn: () => get<{ fills: Fill[] }>("/fills?limit=200"),
    ...LIVE,
  });

export const usePending = () =>
  useQuery({
    queryKey: ["pending"],
    queryFn: () => get<{ pending: PendingOrder[] }>("/pending"),
    refetchInterval: 8_000,
  });

export const useSignals = () =>
  useQuery({
    queryKey: ["signals"],
    queryFn: () => get<{ signals: Signal[] }>("/signals?limit=100"),
    ...LIVE,
  });

export const useAgents = () =>
  useQuery({
    queryKey: ["agents"],
    queryFn: () => get<AgentsResponse>("/agents"),
    refetchInterval: 10_000,
  });

export const useDebates = () =>
  useQuery({
    queryKey: ["debates"],
    queryFn: () => get<{ debates: Debate[] }>("/debates?limit=60"),
    ...LIVE,
  });

export const useDebate = (id: string | null) =>
  useQuery({
    queryKey: ["debate", id],
    queryFn: () =>
      get<{ session: Debate | null; arguments: DebateArgument[] }>(`/debates/${id}`),
    enabled: !!id,
  });

export const useRisk = () =>
  useQuery({ queryKey: ["risk"], queryFn: () => get<RiskResponse>("/risk"), ...LIVE });

export const usePerformance = () =>
  useQuery({
    queryKey: ["performance"],
    queryFn: () =>
      get<{
        periods: Record<string, Record<string, number | string>>;
        latest: Record<string, number | string> | null;
      }>("/performance"),
    refetchInterval: 60_000,
  });

export const useAlerts = () =>
  useQuery({
    queryKey: ["alerts"],
    queryFn: () =>
      get<{
        alerts: {
          id: string;
          rule_name: string;
          severity: string;
          title: string;
          message: string;
          created_at: string;
        }[];
      }>("/alerts?limit=60"),
    refetchInterval: 20_000,
  });

export const useWatchlist = () =>
  useQuery({
    queryKey: ["watchlist"],
    queryFn: () =>
      get<{
        watchlist: {
          symbol: string;
          price: number;
          prev_close: number;
          change_pct: number;
        }[];
      }>("/watchlist"),
    refetchInterval: 20_000,
  });

export const useConfig = () =>
  useQuery({ queryKey: ["config"], queryFn: () => get<Config>("/config") });

export const useCommandVocabulary = () =>
  useQuery({
    queryKey: ["commands"],
    queryFn: () => get<{ commands: string[] }>("/commands"),
    staleTime: Infinity,
  });

export async function runCommand(command: string): Promise<CommandResult> {
  const res = await fetch(`${BASE}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  if (!res.ok) throw new ApiError(`Command failed (${res.status})`, res.status);
  return res.json();
}

/**
 * Every action in the UI is a REPL command, so one mutation covers all of them
 * and every screen refetches once it lands.
 */
export function useCommand() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runCommand,
    onSuccess: () => qc.invalidateQueries(),
  });
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export interface SettingsResult {
  ok: boolean;
  applied: string[];
  errors: string[];
  restart_required: string[];
}

export interface OnboardingState {
  env_exists: boolean;
  completed: boolean;
  has_llm_key: boolean;
  has_broker_key: boolean;
  system_mode: string;
  cio_mode: string;
  initial_capital_usd: number;
  universe: { us: string; india: string; crypto: string };
  missing: string[];
}

export const useOnboarding = () =>
  useQuery({ queryKey: ["onboarding"], queryFn: () => get<OnboardingState>("/onboarding") });

/** Halt or resume trading — the execution agent reads this before every order. */
export function useHalt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { halted: boolean; reason?: string }) =>
      post<{ ok: boolean; halted: boolean }>("/control/halt", input),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Record<string, string | number>) =>
      post<SettingsResult>("/control/settings", { updates }),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useEngineControl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: "start" | "stop" | "restart") =>
      post<{ ok: boolean; running: boolean; agents: number }>("/control/engine", { action }),
    onSuccess: () => qc.invalidateQueries(),
  });
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token A12B3D373865 - verify with scripts/authorship.py verify
