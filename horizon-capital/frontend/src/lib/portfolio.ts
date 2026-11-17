// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-EE4BD20516E4
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
// Pure portfolio math for the Portfolio / Risk / Overview pages.
// positions.weight_pct is 0 in the DB, so weights are always market_value / nav.
import type { Position } from "@/lib/api";
import { money } from "@/lib/format";

export type AllocationRow = {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  marker?: number;
  markerLabel?: string;
};

/** Key of the "Cash" row in allocationRows(), for callers that want positions only. */
export const CASH_KEY = "__cash";

export const isShort = (side: string) => /^(short|sell)$/i.test(side.trim());

/** Position weights in PERCENT of NAV (|market_value| / nav × 100), plus a "Cash" row (cash_usd / nav × 100), sorted desc; marker = maxPositionPct ("limit") on position rows only. nav ≤ 0 → []. */
export function allocationRows(
  positions: Position[],
  nav: number,
  cashUsd: number,
  maxPositionPct: number | null | undefined,
): AllocationRow[] {
  if (!(nav > 0)) return [];
  const hasLimit = maxPositionPct !== null && maxPositionPct !== undefined;
  const rows: AllocationRow[] = positions.map((p) => ({
    key: `${p.symbol}:${p.side}`,
    label: p.symbol,
    sublabel: money(p.market_value),
    value: (Math.abs(p.market_value) / nav) * 100,
    ...(hasLimit ? { marker: maxPositionPct, markerLabel: "limit" } : {}),
  }));
  rows.push({ key: CASH_KEY, label: "Cash", sublabel: money(cashUsd), value: (cashUsd / nav) * 100 });
  return rows.sort((a, b) => b.value - a.value);
}

/** Gross = Σ|mv| / nav, net = (Σ long mv − Σ short mv) / nav (side-aware, lowercase/uppercase tolerant), largest = { symbol, weightPct } or null. */
export function exposure(
  positions: Position[],
  nav: number,
): { gross: number; net: number; largest: { symbol: string; weightPct: number } | null } {
  if (!(nav > 0)) return { gross: 0, net: 0, largest: null };
  let gross = 0;
  let net = 0;
  let largest: { symbol: string; weightPct: number } | null = null;
  for (const p of positions) {
    // ponytail: abs() so a short stored with either sign of market_value nets the same way
    const mv = Math.abs(p.market_value);
    gross += mv;
    net += isShort(p.side) ? -mv : mv;
    const weightPct = (mv / nav) * 100;
    if (!largest || weightPct > largest.weightPct) largest = { symbol: p.symbol, weightPct };
  }
  return { gross: gross / nav, net: net / nav, largest };
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token EE4BD20516E4 - verify with scripts/authorship.py verify
