// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-C058BC779A4C
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { create } from "zustand";

export interface LiveEvent {
  channel: string;
  type: string;
  sender: string;
  timestamp: string | null;
  payload: Record<string, unknown>;
}

interface LiveState {
  connected: boolean;
  events: LiveEvent[];
  setConnected: (connected: boolean) => void;
  push: (event: LiveEvent) => void;
}

/** Rolling in-memory tail of the bus. Nothing is persisted — the DB is the record. */
export const useLiveStore = create<LiveState>((set) => ({
  connected: false,
  events: [],
  setConnected: (connected) => set({ connected }),
  push: (event) =>
    set((state) => ({ events: [event, ...state.events].slice(0, 300) })),
}));

// Heartbeats are every agent every 10s — they would bury everything else in the
// feed. The sidebar's agent gauge already shows what they carry.
const NOISE = new Set(["HEARTBEAT", "HEALTH_CHECK"]);

// Which queries a bus message invalidates. Anything unlisted just lands in the feed.
const REFRESH_ON: Record<string, string[]> = {
  ORDER_NEW: ["orders", "pending", "overview"],
  ORDER_FILL: ["orders", "fills", "positions", "overview", "pending"],
  ORDER_CANCEL: ["orders", "pending"],
  SIGNAL: ["signals"],
  PORTFOLIO_UPDATE: ["overview", "positions", "equity"],
  RISK_ALERT: ["risk", "overview", "alerts"],
  DEBATE_CONCLUSION: ["debates"],
  AGENT_STATUS: ["agents"],
  HEALTH_CHECK: ["alerts"],
  CIO_ADVISORY: ["overview", "alerts"],
};

/**
 * Single websocket for the whole app: it drives the activity feed and tells
 * react-query which caches just went stale, so screens update on events rather
 * than on a timer.
 */
export function useLiveFeed(): void {
  const qc = useQueryClient();
  const setConnected = useLiveStore((s) => s.setConnected);
  const push = useLiveStore((s) => s.push);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    let attempt = 0;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/api/desktop/ws/live`);

      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };

      socket.onmessage = (message) => {
        try {
          const raw = JSON.parse(message.data) as LiveEvent;
          if (raw.channel === "__hello__") return;
          // MessageType values arrive lowercase; normalise once here so every
          // consumer can switch on a single casing.
          const event = { ...raw, type: (raw.type ?? "").toUpperCase() };
          if (!NOISE.has(event.type)) push(event);
          for (const key of REFRESH_ON[event.type] ?? []) {
            qc.invalidateQueries({ queryKey: [key] });
          }
        } catch {
          /* a malformed frame is not worth tearing the socket down for */
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        // Back off to 10s: the backend restarting should not spin the UI.
        attempt += 1;
        retry = setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt));
      };

      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [qc, push, setConnected]);
}

/** Human-readable one-liner for an event in the activity feed. */
export function describeEvent(event: LiveEvent): string {
  const p = event.payload ?? {};
  const symbol = (p.symbol as string) ?? "";
  switch (event.type) {
    case "SIGNAL":
      return `${p.direction ?? "signal"} ${symbol} · ${p.strategy_name ?? p.agent_id ?? ""}`;
    case "ORDER_NEW":
      return `order ${p.side ?? ""} ${p.quantity ?? ""} ${symbol}`;
    case "ORDER_FILL":
      return `filled ${p.filled_qty ?? ""} ${symbol} @ ${p.fill_price ?? ""}`;
    case "ORDER_CANCEL":
      return `cancelled ${symbol || (p.order_id as string) || ""}`;
    case "RISK_ALERT":
      return `${p.alert_type ?? "risk"} ${p.message ?? symbol}`;
    case "DEBATE_CONCLUSION":
      return `debate ${symbol}: ${p.decision ?? p.final_decision ?? ""}`;
    case "DEBATE_START":
      return `debate opened on ${symbol || p.session_id || ""}`;
    case "DEBATE_VOTE":
      return `${p.role ?? p.agent_id ?? "debater"} voted ${p.vote ?? "?"}${
        p.confidence ? ` (${Number(p.confidence).toFixed(2)})` : ""
      }`;
    case "AGENT_STATUS":
      return `${p.agent_id ?? event.sender} ${p.status ?? ""}`;
    case "SETTINGS_UPDATED":
      return `settings changed: ${Object.keys(p).join(", ")}`;
    case "CIO_OVERRIDE":
      return `CIO override: ${p.trigger ?? ""}`;
    case "FEATURE_UPDATE":
      return `features refreshed for ${symbol}`;
    case "PORTFOLIO_UPDATE":
      return `NAV ${p.total_value ?? ""}`;
    case "CIO_ADVISORY":
      return `CIO: ${p.summary ?? p.outlook ?? ""}`;
    case "SENTIMENT_UPDATE":
      return `sentiment ${symbol} ${p.score ?? ""}`;
    case "TICK":
      return `${symbol} ${p.price !== undefined ? Number(p.price).toFixed(2) : ""}`;
    default:
      return `${symbol} ${JSON.stringify(p).slice(0, 90)}`;
  }
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token C058BC779A4C - verify with scripts/authorship.py verify
