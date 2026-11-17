// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-3538F20435E9
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
// Watchlist + research data hooks. Logic only -- markup lives in WatchlistPage.tsx
// so the visual layer can be restyled without touching these.
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { get, post } from "@/lib/api";
import type { CatalogInfo } from "@/lib/api";

export { useWatchlist } from "@/lib/api";
export type { WatchItem, WatchlistResponse, StreamInfo, CatalogInfo } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types -- mirror backend/app/data_layer/{watchlist,market_info}.py
// ---------------------------------------------------------------------------

export interface Quote {
  price: number;
  prev_close: number;
  change_pct: number;
}

export interface CatalogRow {
  symbol: string;
  ticker: string;
  name: string;
  exchange: string;
  asset_class: "us_equity" | "crypto";
  sector: string | null;
  sp500: boolean;
  etf: boolean;
  tradable: boolean;
  on_watchlist: boolean;
}

export interface CatalogCategories {
  groups: { id: string; label: string; count: number }[];
  sectors: { name: string; count: number }[];
  exchanges: { name: string; count: number }[];
  markets: { id: string; label: string; available: boolean; note?: string }[];
  catalog: CatalogInfo;
  note: string;
}

export interface WatchlistChange {
  ok: boolean;
  added?: string[];
  already?: string[];
  rejected?: { symbol: string; reason: string }[];
  removed?: string[];
  missing?: string[];
  count: number;
}

export type HistoryRange = "1M" | "6M" | "1Y" | "5Y";

export interface HistoryBar {
  time: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface HistoryResponse {
  symbol: string;
  range: HistoryRange;
  source: "alpaca" | "yahoo" | null;
  bars: HistoryBar[];
}

export interface SymbolDetail {
  symbol: string;
  ticker: string;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  asset_class: string | null;
  tradable: boolean;
  in_catalog: boolean;
  on_watchlist: boolean;
  quote: Quote;
  stats: {
    high_52w: number | null;
    low_52w: number | null;
    avg_volume_30d: number | null;
    volume: number | null;
  };
  history_source: "alpaca" | "yahoo" | null;
  sentiment: { label: string; score: number; timestamp: string | null } | null;
  news: string[];
}

/** One row in any Recommended list: identity + live price + watchlist state. */
export interface PricedRow extends Quote {
  symbol: string;
  ticker: string;
  name: string | null;
  exchange: string | null;
  tradable: boolean;
  on_watchlist: boolean;
}

export interface StrategyPick extends PricedRow {
  weight: number;
  sleeve: string | null;
  reason: string;
  as_of: string | null;
  held: boolean;
}

export interface Recommended {
  strategy: { source: "live" | "signals"; picks: StrategyPick[] };
  movers: {
    gainers: PricedRow[];
    losers: PricedRow[];
    most_actives: PricedRow[];
    last_updated: string | null;
    error: string | null;
    filter?: string;
  };
  sentiment: (PricedRow & { sentiment: { label: string; score: number } })[];
  generated_at: string;
  disclaimer: string;
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export const useCatalogCategories = () =>
  useQuery({
    queryKey: ["catalog", "categories"],
    queryFn: () => get<CatalogCategories>("/watchlist/categories"),
    staleTime: 60_000,
  });

/** Server-side search: the catalog is ~14k rows, so only one page crosses the wire. */
export const useCatalogSearch = (filters: { q: string; group: string; sector: string }) =>
  useInfiniteQuery({
    queryKey: ["catalog", "search", filters],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ offset: String(pageParam), limit: "50" });
      if (filters.q) params.set("q", filters.q);
      if (filters.group) params.set("group", filters.group);
      if (filters.sector) params.set("sector", filters.sector);
      return get<{ results: CatalogRow[]; total: number; offset: number; limit: number }>(
        `/watchlist/search?${params}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.results.length < last.total ? last.offset + last.limit : undefined,
    placeholderData: keepPreviousData,
  });

/**
 * Prices for whatever is on screen. The backend batches them into Alpaca snapshot
 * calls and caches ~20s; nothing here subscribes the background feeds.
 */
export function useQuotes(symbols: string[]) {
  const key = [...new Set(symbols)].sort().join(",");
  return useQuery({
    queryKey: ["quotes", key],
    queryFn: () =>
      get<{ quotes: Record<string, Quote> }>(`/quotes?symbols=${encodeURIComponent(key)}`),
    enabled: key.length > 0,
    staleTime: 20_000,
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
    select: (data) => data.quotes,
  });
}

export const useSymbolDetail = (symbol: string | null) =>
  useQuery({
    queryKey: ["symbol", symbol],
    queryFn: () => get<SymbolDetail>(`/symbol/${encodeURIComponent(symbol!)}`),
    enabled: !!symbol,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

export const useSymbolHistory = (symbol: string | null, range: HistoryRange) =>
  useQuery({
    queryKey: ["symbol", symbol, "history", range],
    queryFn: () =>
      get<HistoryResponse>(`/symbol/${encodeURIComponent(symbol!)}/history?range=${range}`),
    enabled: !!symbol,
    staleTime: 600_000, // daily bars; the backend caches 10 min too
    placeholderData: keepPreviousData,
  });

export const useRecommended = (enabled = true) =>
  useQuery({
    queryKey: ["catalog", "recommended"],
    queryFn: () => get<Recommended>("/watchlist/recommended"),
    enabled,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

// ---------------------------------------------------------------------------
// Mutations + local state
// ---------------------------------------------------------------------------

/** Add/remove go through the same backend path as the REPL's `watchlist add|remove`. */
export function useWatchlistChange() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { action: "add" | "remove"; symbols: string[] }) =>
      post<WatchlistChange>(`/watchlist/${input.action}`, { symbols: input.symbols }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["catalog"] });
      qc.invalidateQueries({ queryKey: ["symbol"] });
    },
  });
}

/** Multi-select over symbols, shared by the catalog list and the watchlist. */
export function useSymbolSelection() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = useCallback(
    (symbol: string) =>
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(symbol)) next.delete(symbol);
        else next.add(symbol);
        return next;
      }),
    [],
  );
  const clear = useCallback(() => setSelected(new Set()), []);
  const setAll = useCallback((symbols: string[]) => setSelected(new Set(symbols)), []);
  return { selected, toggle, clear, setAll };
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 3538F20435E9 - verify with scripts/authorship.py verify
