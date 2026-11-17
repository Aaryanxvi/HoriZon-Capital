// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-F47B20E1B7A8
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";

// Read-only chart aggregations — backend/app/api/desktop_viz.py.
const BASE = "/api/desktop/viz";

// ponytail: duplicate of api.ts `get` (that file was mid-edit by another agent); fold into an
// exported `get` once it settles.
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new ApiError(`${path} failed (${res.status})`, res.status);
  return res.json() as Promise<T>;
}

export interface NavDailyPoint {
  date: string; // YYYY-MM-DD, last snapshot of that UTC day
  nav: number;
  cash_usd: number;
  equity_value: number;
}

export interface BenchmarkPoint {
  date: string;
  close: number;
}

export interface SleeveSignal {
  symbol: string;
  weight: number; // portfolio weight (sleeve weight × in-sleeve weight)
}

export interface Sleeve {
  name: string;
  weight: number;
  cadence_days: number;
  last_refresh: string | null;
  signals: SleeveSignal[];
}

export interface SleevesResponse {
  available: boolean;
  market_open: boolean | null;
  sleeves: Sleeve[];
  targets: Record<string, number>;
}

export const useNavDaily = () =>
  useQuery({
    queryKey: ["viz", "nav-daily"],
    queryFn: () => get<{ points: NavDailyPoint[]; days_recorded: number }>("/nav-daily"),
    staleTime: 60_000,
    refetchInterval: 300_000,
  });

export type BenchmarkRange = "1M" | "6M" | "1Y" | "5Y";

const BENCHMARK_DAYS: Record<BenchmarkRange, number> = { "1M": 31, "6M": 183, "1Y": 366, "5Y": 1830 };

export const useBenchmark = (symbol = "SPY", range: BenchmarkRange = "5Y") =>
  useQuery({
    queryKey: ["viz", "benchmark", symbol, range],
    queryFn: () =>
      get<{ symbol: string; points: BenchmarkPoint[]; source?: string }>(
        `/benchmark?symbol=${encodeURIComponent(symbol)}&days=${BENCHMARK_DAYS[range]}`,
      ),
    staleTime: 60_000,
    refetchInterval: 300_000,
  });

export const useSleeves = () =>
  useQuery({
    queryKey: ["viz", "sleeves"],
    queryFn: () => get<SleevesResponse>("/sleeves"),
    staleTime: 60_000,
    refetchInterval: 30_000,
  });
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token F47B20E1B7A8 - verify with scripts/authorship.py verify
