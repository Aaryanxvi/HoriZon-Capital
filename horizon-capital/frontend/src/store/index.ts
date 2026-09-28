// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-1BCBEEB98698
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { create } from "zustand";
import type {
  User,
  PortfolioSummary,
  Position,
  Agent,
  Trade,
  RiskMetrics,
  SystemMode,
} from "@/api/client";
import { login as apiLogin, getAgents } from "@/api/client";
import wsManager from "@/api/websocket";

// ---------------------------------------------------------------------------
// Auth Store
// ---------------------------------------------------------------------------

interface AuthState {
  token: string | null;
  user: User | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem("token"),
  user: null,

  login: async (username: string, password: string) => {
    const response = await apiLogin({ username, password });
    localStorage.setItem("token", response.access_token);
    set({ token: response.access_token });
  },

  logout: () => {
    localStorage.removeItem("token");
    set({ token: null, user: null });
  },

  setUser: (user: User) => set({ user }),
}));

// ---------------------------------------------------------------------------
// Portfolio Store
// ---------------------------------------------------------------------------

interface PortfolioState {
  summary: PortfolioSummary | null;
  positions: Position[];
  setSummary: (summary: PortfolioSummary) => void;
  setPositions: (positions: Position[]) => void;
  updateFromWS: (data: Partial<PortfolioSummary>) => void;
}

export const usePortfolioStore = create<PortfolioState>((set, get) => ({
  summary: null,
  positions: [],

  setSummary: (summary) => set({ summary }),
  setPositions: (positions) => set({ positions }),

  updateFromWS: (data) => {
    const current = get().summary;
    if (current) {
      set({ summary: { ...current, ...data } });
    }
  },
}));

// ---------------------------------------------------------------------------
// Agent Store
// ---------------------------------------------------------------------------

interface AgentState {
  agents: Agent[];
  loading: boolean;
  setAgents: (agents: Agent[]) => void;
  updateAgent: (agentId: string, updates: Partial<Agent>) => void;
  fetchAgents: () => Promise<void>;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  agents: [],
  loading: false,

  setAgents: (agents) => set({ agents }),

  updateAgent: (agentId, updates) => {
    const agents = get().agents.map((a) =>
      a.id === agentId ? { ...a, ...updates } : a
    );
    set({ agents });
  },

  fetchAgents: async () => {
    set({ loading: true });
    try {
      const agents = await getAgents();
      set({ agents, loading: false });
    } catch {
      set({ loading: false });
    }
  },
}));

let _agentPollingInterval: ReturnType<typeof setInterval> | null = null;
let _wsUnsub: (() => void) | null = null;

/**
 * Start polling agents every 10s + subscribe to WebSocket agent updates.
 * Call once on app mount. Returns a cleanup function.
 */
export function initAgentPolling(): () => void {
  const store = useAgentStore.getState();
  store.fetchAgents();

  _agentPollingInterval = setInterval(() => {
    useAgentStore.getState().fetchAgents();
  }, 10_000);

  // Subscribe to WebSocket agent status updates
  _wsUnsub = wsManager.subscribe("horizon.agent.*", (data: unknown) => {
    const msg = data as { agent_id?: string; status?: string };
    if (msg.agent_id && msg.status) {
      const statusMap: Record<string, "active" | "paused" | "error"> = {
        RUNNING: "active",
        PAUSED: "paused",
        CRASHED: "error",
        ERROR: "error",
      };
      useAgentStore.getState().updateAgent(msg.agent_id, {
        status: statusMap[msg.status] ?? "active",
      });
    }
  });

  return () => {
    if (_agentPollingInterval) {
      clearInterval(_agentPollingInterval);
      _agentPollingInterval = null;
    }
    if (_wsUnsub) {
      _wsUnsub();
      _wsUnsub = null;
    }
  };
}

// ---------------------------------------------------------------------------
// Trade Store
// ---------------------------------------------------------------------------

interface TradeState {
  trades: Trade[];
  pendingApprovals: Trade[];
  setTrades: (trades: Trade[]) => void;
  setPendingApprovals: (trades: Trade[]) => void;
  addTrade: (trade: Trade) => void;
  updateTrade: (tradeId: string, updates: Partial<Trade>) => void;
}

export const useTradeStore = create<TradeState>((set, get) => ({
  trades: [],
  pendingApprovals: [],

  setTrades: (trades) => set({ trades }),
  setPendingApprovals: (trades) => set({ pendingApprovals: trades }),

  addTrade: (trade) => {
    set({ trades: [trade, ...get().trades] });
    if (trade.status === "pending") {
      set({ pendingApprovals: [trade, ...get().pendingApprovals] });
    }
  },

  updateTrade: (tradeId, updates) => {
    const trades = get().trades.map((t) =>
      t.id === tradeId ? { ...t, ...updates } : t
    );
    const pendingApprovals = trades.filter((t) => t.status === "pending");
    set({ trades, pendingApprovals });
  },
}));

// ---------------------------------------------------------------------------
// Risk Store
// ---------------------------------------------------------------------------

interface RiskState {
  metrics: RiskMetrics | null;
  killSwitchActive: boolean;
  setMetrics: (metrics: RiskMetrics) => void;
  setKillSwitch: (active: boolean) => void;
}

export const useRiskStore = create<RiskState>((set) => ({
  metrics: null,
  killSwitchActive: false,

  setMetrics: (metrics) =>
    set({ metrics, killSwitchActive: metrics.kill_switch_active }),

  setKillSwitch: (active) => set({ killSwitchActive: active }),
}));

// ---------------------------------------------------------------------------
// System Store
// ---------------------------------------------------------------------------

interface SystemState {
  mode: SystemMode;
  connected: boolean;
  setMode: (mode: SystemMode) => void;
  setConnected: (connected: boolean) => void;
}

export const useSystemStore = create<SystemState>((set) => ({
  mode: "supervised",
  connected: false,

  setMode: (mode) => set({ mode }),
  setConnected: (connected) => set({ connected }),
}));
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 1BCBEEB98698 - verify with scripts/authorship.py verify
