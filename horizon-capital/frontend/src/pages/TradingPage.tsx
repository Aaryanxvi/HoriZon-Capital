// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-2B90E3F69E58
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Check, Send, X } from "lucide-react";
import { useCallback, useState } from "react";

import { useCommand, useFills, useOrders, usePending } from "@/lib/api";
import { dateTime, money, num, timeAgo } from "@/lib/format";
import { ChartCard, Timeline, type TimelineEvent } from "@/components/charts";
import TradeTimeline from "@/components/TradeTimeline";
import {
  Badge,
  Card,
  CommandEcho,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Segmented,
  StatusChip,
  statusTone,
  Table,
  type StatusChipTone,
} from "@/components/ui";

type Tab = "pending" | "orders" | "fills";

const CHIP: Record<string, StatusChipTone> = {
  good: "ok",
  bad: "critical",
  warn: "warning",
  neutral: "neutral",
};

const WEEK = 7 * 86_400;

// Backend timestamps may omit the zone; they are UTC (same rule as format.ts).
const unix = (iso: string) =>
  new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime() / 1000;

/** Blotter row that opens the trade timeline — clickable and keyboard-reachable. */
const openRow = (open: () => void, label: string) => ({
  className: "row-hover cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
  tabIndex: 0,
  "aria-label": label,
  onClick: open,
  onKeyDown: (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  },
});

const qty = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 4 });

function sideOf(side: string | null | undefined): "BUY" | "SELL" | null {
  const s = (side ?? "").toUpperCase();
  return s === "BUY" || s === "SELL" ? s : null;
}

/** Side is up/down colour, so it always travels with its glyph. */
function SideChip({ side }: { side: string | null | undefined }) {
  const s = sideOf(side);
  if (!s) return side ? <Badge>{side}</Badge> : <span className="text-ink-3">—</span>;
  const up = s === "BUY";
  return (
    <Badge
      className={up ? "!border-up/30 !bg-up/10" : "!border-down/30 !bg-down/10"}
      icon={
        <span aria-hidden className={up ? "text-up" : "text-down"}>
          {up ? "▲" : "▼"}
        </span>
      }
    >
      {side}
    </Badge>
  );
}

/** Manual ticket. Sends the same `buy`/`sell` command the terminal accepts, so
 *  every guard (cash, kill switch, naked short) applies unchanged. */
function ManualTicket({ onResult }: { onResult: (html: string, text: string) => void }) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [symbol, setSymbol] = useState("");
  const [quantity, setQuantity] = useState("");
  const command = useCommand();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!symbol.trim() || !quantity.trim()) return;
    command.mutate(`${side} ${symbol.trim().toUpperCase()} ${quantity.trim()}`, {
      onSuccess: (result) => {
        onResult(result.html, result.text);
        setQuantity("");
      },
    });
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <Segmented
        ariaLabel="Order side"
        size="md"
        value={side}
        onChange={setSide}
        options={[
          { value: "buy", label: "▲ Buy", activeClassName: "!border-up/40 !bg-up/10 text-up" },
          { value: "sell", label: "▼ Sell", activeClassName: "!border-down/40 !bg-down/10 text-down" },
        ]}
      />
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="Symbol"
        aria-label="Symbol"
        className="input w-32 uppercase"
      />
      <input
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder="Qty"
        aria-label="Quantity"
        inputMode="decimal"
        className="input nums w-24"
      />
      <button type="submit" className="btn btn-primary" disabled={command.isPending}>
        <Send className="h-3.5 w-3.5" />
        {command.isPending ? "Sending" : "Send order"}
      </button>
    </form>
  );
}

function ActivityCard() {
  const ordersQ = useOrders();
  const fillsQ = useFills();
  const orders = ordersQ.data?.orders ?? [];
  const fills = fillsQ.data?.fills ?? [];
  const since = Date.now() / 1000 - WEEK;

  const orderById = new Map(orders.map((o) => [o.id, o]));
  const fillPrice = new Map(fills.map((f) => [f.order_id, f.fill_price]));
  const events: TimelineEvent[] = [];
  for (const f of fills) {
    const order = orderById.get(f.order_id);
    const side = sideOf(f.side ?? order?.side);
    const symbol = f.symbol ?? order?.symbol;
    const time = unix(f.filled_at);
    if (!side || !symbol || !(time >= since)) continue;
    events.push({
      time,
      symbol,
      side,
      kind: "fill",
      size: f.notional,
      label: `filled ${qty(f.filled_qty)} ${symbol} @ ${money(f.fill_price)}`,
    });
  }
  for (const o of orders) {
    const side = sideOf(o.side);
    const time = unix(o.created_at);
    if (!side || !(time >= since)) continue;
    events.push({
      time,
      symbol: o.symbol,
      side,
      kind: "order",
      size: o.quantity * (o.limit_price ?? fillPrice.get(o.id) ?? 1),
      label: `${o.status.toLowerCase()} ${side.toLowerCase()} ${qty(o.quantity)} ${o.symbol}`,
    });
  }
  const fillCount = events.filter((e) => e.kind === "fill").length;
  const error = ordersQ.error ?? fillsQ.error;

  return (
    <ChartCard
      title="Activity · last 7 days"
      subtitle={
        events.length ? `${events.length - fillCount} orders · ${fillCount} fills` : undefined
      }
      isLoading={ordersQ.isLoading || fillsQ.isLoading}
      isFetching={ordersQ.isFetching || fillsQ.isFetching}
      error={error ? `Could not load order activity — ${error.message}` : null}
      empty={
        events.length
          ? null
          : {
              message: "No orders in the last 7 days",
              hint: "Agent and manual orders appear here as they are placed, fills once the broker confirms them.",
            }
      }
      table={{
        columns: ["Time", "Symbol", "Event"],
        rows: [...events]
          .sort((a, b) => b.time - a.time)
          .map((e) => [dateTime(new Date(e.time * 1000).toISOString()), e.symbol, e.label]),
      }}
    >
      <Timeline events={events} />
    </ChartCard>
  );
}

export default function TradingPage() {
  const [picked, setTab] = useState<Tab | null>(null);
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);
  const [traced, setTraced] = useState<string | null>(null);
  const closeTrace = useCallback(() => setTraced(null), []);

  const { data: pending, isLoading: pendingLoading, error: pendingError } = usePending();
  const { data: orders, isLoading: ordersLoading, error: ordersError } = useOrders();
  const { data: fills, isLoading: fillsLoading, error: fillsError } = useFills();
  const command = useCommand();

  const decide = (verb: "approve" | "reject", orderId: string) =>
    command.mutate(`${verb} ${orderId}`, {
      onSuccess: (result) => setEcho({ html: result.html, text: result.text }),
    });

  const pendingCount = pending?.pending.length ?? 0;
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "pending", label: "Pending", count: pendingCount },
    { key: "orders", label: "Orders", count: orders?.orders.length },
    { key: "fills", label: "Fills", count: fills?.fills.length },
  ];
  // Until you pick one, open on the first tab with rows (Pending first: approvals matter most).
  const tab = picked ?? tabs.find((t) => t.count)?.key ?? "pending";

  const failed = (what: string, error: Error) => (
    <div className="p-3">
      <ErrorNote message={`Could not load ${what} — ${error.message}`} />
    </div>
  );

  return (
    <>
      <PageHeader
        title="Trading"
        subtitle="Orders route through the risk, debate and execution gates exactly as they do in the terminal"
      />

      <div className="flex flex-col gap-3">
        <Card title="Manual ticket" subtitle="Sized and guarded like any agent order">
          <div className="space-y-3">
            <ManualTicket onResult={(html, text) => setEcho({ html, text })} />
            {echo && (
              <CommandEcho html={echo.html} text={echo.text} onDismiss={() => setEcho(null)} />
            )}
          </div>
        </Card>

        <ActivityCard />

        <Card
          title="Blotter"
          subtitle={tab === "pending" ? undefined : "Select a row to trace it from signal to P&L"}
          bodyClassName=""
          action={
            <Segmented
              ariaLabel="Blotter view"
              size="md"
              value={tab}
              onChange={setTab}
              options={tabs.map((t) => ({
                value: t.key,
                label: (
                  <>
                    {t.label}
                    {t.count !== undefined && t.count > 0 && (
                      <span className="nums ml-1.5 text-ink-3">{t.count}</span>
                    )}
                  </>
                ),
              }))}
            />
          }
        >
          {tab === "pending" &&
            (pendingLoading ? (
              <Loading />
            ) : pendingError ? (
              failed("pending approvals", pendingError)
            ) : pendingCount === 0 ? (
              <Empty
                message="Nothing waiting on you"
                hint="Orders queue here only in HUMAN_APPROVAL mode."
              />
            ) : (
              <ul className="divide-y divide-line">
                {pending!.pending.map((order) => (
                  <li
                    key={order.order_id}
                    className="flex flex-wrap items-center justify-between gap-3 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <SideChip side={order.side} />
                        <span className="text-sm font-medium text-ink">{order.symbol ?? "—"}</span>
                        <span className="nums text-sm text-ink-2">
                          {order.quantity !== undefined ? num(Number(order.quantity), 2) : ""}
                        </span>
                      </div>
                      <div className="nums mt-0.5 font-mono text-2xs text-ink-3">
                        {order.order_id} · {timeAgo(order.created_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => decide("approve", order.order_id)}
                        disabled={command.isPending}
                        className="btn btn-primary"
                      >
                        <Check className="h-3.5 w-3.5" /> Approve
                      </button>
                      <button
                        onClick={() => decide("reject", order.order_id)}
                        disabled={command.isPending}
                        className="btn"
                      >
                        <X className="h-3.5 w-3.5" /> Reject
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ))}

          {tab === "orders" &&
            (ordersLoading ? (
              <Loading />
            ) : ordersError ? (
              failed("orders", ordersError)
            ) : !orders?.orders.length ? (
              <Empty message="No orders yet" hint="Orders appear once an agent or the manual ticket places one." />
            ) : (
              <Table
                className="max-h-[560px]"
                head={["Symbol", "Side", "Qty", "Type", "Status", "Broker", "Placed"]}
                align={["left", "left", "right", "left", "left", "left", "right"]}
              >
                {orders.orders.map((order) => (
                  <tr
                    key={order.id}
                    {...openRow(() => setTraced(order.id), `Trace ${order.side} ${order.symbol} order`)}
                  >
                    <td className="td">
                      <div className="font-medium">{order.symbol}</div>
                      <div className="text-2xs uppercase text-ink-3">{order.exchange}</div>
                    </td>
                    <td className="td">
                      <SideChip side={order.side} />
                    </td>
                    <td className="td nums text-right">{num(order.quantity, 2)}</td>
                    <td className="td text-xs uppercase text-ink-2">{order.order_type}</td>
                    <td className="td">
                      <StatusChip tone={CHIP[statusTone(order.status)]} label={order.status} />
                      {order.rejection_reason && (
                        <div
                          className="mt-0.5 max-w-[240px] truncate text-2xs text-crit"
                          title={order.rejection_reason}
                        >
                          {order.rejection_reason}
                        </div>
                      )}
                    </td>
                    <td className="td text-xs text-ink-2">{order.broker}</td>
                    <td className="td nums text-right text-xs text-ink-2">
                      {dateTime(order.created_at)}
                    </td>
                  </tr>
                ))}
              </Table>
            ))}

          {tab === "fills" &&
            (fillsLoading ? (
              <Loading />
            ) : fillsError ? (
              failed("fills", fillsError)
            ) : !fills?.fills.length ? (
              <Empty message="No fills yet" hint="Fills land when the broker confirms an order." />
            ) : (
              <Table
                className="max-h-[560px]"
                head={["Symbol", "Side", "Qty", "Price", "Notional", "Slippage", "Filled"]}
                align={["left", "left", "right", "right", "right", "right", "right"]}
              >
                {fills.fills.map((fill) => (
                  <tr
                    key={fill.id}
                    {...openRow(() => setTraced(fill.order_id), `Trace ${fill.side ?? ""} ${fill.symbol ?? ""} fill`)}
                  >
                    <td className="td font-medium">{fill.symbol ?? "—"}</td>
                    <td className="td">
                      <SideChip side={fill.side} />
                    </td>
                    <td className="td nums text-right">{num(fill.filled_qty, 4)}</td>
                    <td className="td nums text-right">{money(fill.fill_price)}</td>
                    <td className="td nums text-right">{money(fill.notional)}</td>
                    <td className="td nums text-right text-xs text-ink-2">
                      {num(fill.slippage, 4)}
                    </td>
                    <td className="td nums text-right text-xs text-ink-2">
                      {dateTime(fill.filled_at)}
                    </td>
                  </tr>
                ))}
              </Table>
            ))}
        </Card>
      </div>
      {traced && <TradeTimeline orderId={traced} onClose={closeTrace} />}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 2B90E3F69E58 - verify with scripts/authorship.py verify
