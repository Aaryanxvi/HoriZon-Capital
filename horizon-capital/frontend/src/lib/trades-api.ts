import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api";

// One order's life, signal -> P&L — backend/app/api/desktop_trades.py.

export type StepKey = "signal" | "risk" | "debate" | "order" | "fill" | "pnl";

export interface TimelineStep {
  key: StepKey;
  /** done = happened · blocked = stopped the trade here · skipped = never applies · unknown = not recorded */
  status: "done" | "blocked" | "skipped" | "unknown";
  at: string | null;
  /** id = stored foreign key · time = nearest same symbol + side within a window */
  link: "id" | "time" | null;
  note: string | null;
  // Shape depends on `key`; see the backend for the fields each step carries.
  detail: Record<string, any>;
}

export interface TradeTimeline {
  order_id: string;
  symbol: string;
  side: string;
  status: string;
  steps: TimelineStep[];
}

export const useTradeTimeline = (orderId: string | null) =>
  useQuery({
    queryKey: ["trades", "timeline", orderId],
    queryFn: () => get<TradeTimeline>(`/trades/${encodeURIComponent(orderId!)}/timeline`),
    enabled: !!orderId,
    staleTime: 10_000,
    refetchInterval: 30_000, // P&L mark moves
  });
