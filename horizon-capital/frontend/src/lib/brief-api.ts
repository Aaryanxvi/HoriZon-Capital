import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import type { Sleeve } from "@/lib/viz-api";

// Morning brief + regime gauge — backend/app/api/desktop_brief.py.
const BASE = "/api/desktop/brief";

// ponytail: same local `get` as viz-api.ts; fold both into an exported api.ts helper later.
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

/** Rich colour name from the terminal brief: "green" | "red" | "yellow" | "dim" | null. */
export type BriefSegment = [text: string, tone: string | null];

export interface BriefSection {
  title: string;
  lines: BriefSegment[][];
}

export interface Brief {
  date: string;
  generated_at: string;
  sections: BriefSection[];
}

export type RegimeState = "RISK_ON" | "RISK_OFF";

export interface RegimeDay {
  date: string;
  state: RegimeState;
  p_risk_on: number;
}

export interface Regime {
  available: boolean;
  /** "computed" = fitted now from stored SPY daily bars; "stored" = last logged regime. */
  source: "computed" | "stored" | null;
  state: RegimeState | null;
  /** Posterior of the risk-on cluster, 0..1 (> 0.5 = RISK_ON). */
  p_risk_on: number | null;
  as_of: string | null;
  history: RegimeDay[];
  /** true = the running strategy agent's sleeves; false = the configured mix (engine off). */
  sleeves_live: boolean;
  sleeves: Sleeve[];
}

// The brief logs the regime it computes, so it is fetched on mount only — not polled.
export const useBrief = () =>
  useQuery({
    queryKey: ["brief"],
    queryFn: () => get<Brief>(""),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

export const useRegime = () =>
  useQuery({
    queryKey: ["brief", "regime"],
    queryFn: () => get<Regime>("/regime"),
    staleTime: 60_000,
    refetchInterval: 300_000,
  });
