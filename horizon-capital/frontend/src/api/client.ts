import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

const api: AxiosInstance = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

// Attach JWT on every request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem("token");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Redirect to /login on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

// ---------------------------------------------------------------------------
// Types (mirrors backend schemas – kept lightweight)
// ---------------------------------------------------------------------------

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  username: string;
  role: string;
}

export interface PortfolioSummary {
  total_value: number;
  cash: number;
  pnl_today: number;
  pnl_total: number;
  sharpe_ratio: number;
  max_drawdown: number;
  positions_count: number;
  updated_at: string;
}

export interface Position {
  id: string;
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  weight: number;
}

export interface Signal {
  id: string;
  agent_id: string;
  agent_name: string;
  symbol: string;
  direction: "buy" | "sell" | "hold";
  conviction: number;
  reasoning: string;
  created_at: string;
}

export interface Trade {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  status: "pending" | "approved" | "rejected" | "executed" | "failed";
  source_agent: string;
  created_at: string;
  executed_at?: string;
}

export interface RiskMetrics {
  portfolio_var: number;
  portfolio_cvar: number;
  beta: number;
  correlation_risk: number;
  concentration_risk: number;
  liquidity_risk: number;
  sector_exposure: Record<string, number>;
  drawdown_current: number;
  drawdown_max: number;
  kill_switch_active: boolean;
  updated_at: string;
}

export interface Agent {
  id: string;
  name: string;
  type: string;
  status: "active" | "paused" | "error";
  last_signal_at?: string;
  signals_today: number;
  accuracy_30d: number;
  description: string;
}

export interface DebateSession {
  id: string;
  topic: string;
  status: "active" | "concluded";
  consensus?: string;
  created_at: string;
  arguments_count: number;
}

export interface DebateArgument {
  id: string;
  session_id: string;
  agent_name: string;
  position: "bull" | "bear" | "neutral";
  argument: string;
  confidence: number;
  created_at: string;
}

export interface Narrative {
  id: string;
  title: string;
  summary: string;
  sentiment: number;
  impact: "high" | "medium" | "low";
  sources: string[];
  created_at: string;
}

export interface SentimentData {
  overall: number;
  by_sector: Record<string, number>;
  trending_topics: string[];
  updated_at: string;
}

export interface PerformanceData {
  equity_curve: { date: string; value: number }[];
  daily_returns: { date: string; return_pct: number }[];
  monthly_returns: { month: string; return_pct: number }[];
  metrics: {
    total_return: number;
    annualized_return: number;
    sharpe_ratio: number;
    sortino_ratio: number;
    max_drawdown: number;
    win_rate: number;
    profit_factor: number;
    avg_trade_pnl: number;
  };
}

export type SystemMode = "autonomous" | "supervised" | "manual";

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

// Auth
export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>("/auth/login", data);
  return res.data;
}

export async function getCurrentUser(): Promise<User> {
  const res = await api.get<User>("/auth/me");
  return res.data;
}

// Portfolio
export async function getPortfolio(): Promise<PortfolioSummary> {
  const res = await api.get<PortfolioSummary>("/portfolio/summary");
  return res.data;
}

export async function getPositions(): Promise<Position[]> {
  const res = await api.get<Position[]>("/portfolio/positions");
  return res.data;
}

// Signals
export async function getSignals(params?: {
  agent_id?: string;
  symbol?: string;
  limit?: number;
}): Promise<Signal[]> {
  const res = await api.get<Signal[]>("/signals", { params });
  return res.data;
}

// Trades
export async function getTrades(params?: {
  status?: string;
  limit?: number;
}): Promise<Trade[]> {
  const res = await api.get<Trade[]>("/trades", { params });
  return res.data;
}

export async function approveTrade(tradeId: string): Promise<Trade> {
  const res = await api.post<Trade>(`/trades/${tradeId}/approve`);
  return res.data;
}

export async function rejectTrade(tradeId: string): Promise<Trade> {
  const res = await api.post<Trade>(`/trades/${tradeId}/reject`);
  return res.data;
}

// Risk
export async function getRiskMetrics(): Promise<RiskMetrics> {
  const res = await api.get<RiskMetrics>("/risk/metrics");
  return res.data;
}

// Agents
export async function getAgents(): Promise<Agent[]> {
  const res = await api.get<Agent[]>("/agents");
  return res.data;
}

export async function pauseAgent(agentId: string): Promise<Agent> {
  const res = await api.post<Agent>(`/agents/${agentId}/pause`);
  return res.data;
}

export async function resumeAgent(agentId: string): Promise<Agent> {
  const res = await api.post<Agent>(`/agents/${agentId}/resume`);
  return res.data;
}

// Debate
export async function getDebateSessions(): Promise<DebateSession[]> {
  const res = await api.get<DebateSession[]>("/debate/sessions");
  return res.data;
}

export async function getDebateArguments(
  sessionId: string
): Promise<DebateArgument[]> {
  const res = await api.get<DebateArgument[]>(
    `/debate/sessions/${sessionId}/arguments`
  );
  return res.data;
}

// Sentiment & Narratives
export async function getNarratives(): Promise<Narrative[]> {
  const res = await api.get<Narrative[]>("/sentiment/narratives");
  return res.data;
}

export async function getSentiment(): Promise<SentimentData> {
  const res = await api.get<SentimentData>("/sentiment/overview");
  return res.data;
}

// Performance
export async function getPerformance(params?: {
  period?: string;
}): Promise<PerformanceData> {
  const res = await api.get<PerformanceData>("/performance", { params });
  return res.data;
}

// System
export async function setMode(mode: SystemMode): Promise<{ mode: SystemMode }> {
  const res = await api.post<{ mode: SystemMode }>("/system/mode", { mode });
  return res.data;
}

export async function activateKillSwitch(): Promise<{ active: boolean }> {
  const res = await api.post<{ active: boolean }>("/system/kill-switch");
  return res.data;
}

export async function deactivateKillSwitch(): Promise<{ active: boolean }> {
  const res = await api.delete<{ active: boolean }>("/system/kill-switch");
  return res.data;
}

export default api;
