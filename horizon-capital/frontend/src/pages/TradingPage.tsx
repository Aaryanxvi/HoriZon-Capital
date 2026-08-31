import clsx from "clsx";
import { Check, Send, X } from "lucide-react";
import { useState } from "react";

import { useCommand, useFills, useOrders, usePending } from "@/lib/api";
import { dateTime, money, num, timeAgo } from "@/lib/format";
import {
  Badge,
  Card,
  CommandEcho,
  Empty,
  Loading,
  PageHeader,
  statusTone,
  Table,
} from "@/components/ui";

type Tab = "pending" | "orders" | "fills";

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
      <div className="flex overflow-hidden rounded-lg border border-line">
        {(["buy", "sell"] as const).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setSide(option)}
            className={clsx(
              "px-3 py-1.5 text-sm font-medium capitalize transition",
              side === option
                ? option === "buy"
                  ? "bg-up text-white"
                  : "bg-down text-white"
                : "bg-surface text-soft hover:bg-raised",
            )}
          >
            {option}
          </button>
        ))}
      </div>
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="Symbol"
        className="w-32 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm uppercase text-ink placeholder:text-faint"
      />
      <input
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder="Qty"
        inputMode="decimal"
        className="nums w-24 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-faint"
      />
      <button type="submit" className="btn btn-primary" disabled={command.isPending}>
        <Send className="h-3.5 w-3.5" />
        {command.isPending ? "Sending" : "Send order"}
      </button>
    </form>
  );
}

export default function TradingPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);

  const { data: pending, isLoading: pendingLoading } = usePending();
  const { data: orders, isLoading: ordersLoading } = useOrders();
  const { data: fills, isLoading: fillsLoading } = useFills();
  const command = useCommand();

  const decide = (verb: "approve" | "reject", orderId: string) =>
    command.mutate(`${verb} ${orderId}`, {
      onSuccess: (result) => setEcho({ html: result.html, text: result.text }),
    });

  const pendingCount = pending?.pending.length ?? 0;
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "pending", label: "Awaiting approval", count: pendingCount },
    { key: "orders", label: "Orders", count: orders?.orders.length },
    { key: "fills", label: "Fills", count: fills?.fills.length },
  ];

  return (
    <>
      <PageHeader
        title="Trading"
        subtitle="Orders route through the risk, debate and execution gates exactly as they do in the terminal"
      />

      <Card className="mb-4" title="Manual ticket" subtitle="Sized and guarded like any agent order">
        <div className="space-y-3">
          <ManualTicket onResult={(html, text) => setEcho({ html, text })} />
          {echo && (
            <CommandEcho html={echo.html} text={echo.text} onDismiss={() => setEcho(null)} />
          )}
        </div>
      </Card>

      <div className="mb-3 flex items-center gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              "-mb-px border-b-2 px-3 py-2 text-sm transition",
              tab === t.key
                ? "border-clay font-medium text-ink"
                : "border-transparent text-soft hover:text-ink",
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className="nums ml-1.5 text-xs text-faint">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "pending" && (
        <Card bodyClassName="">
          {pendingLoading ? (
            <Loading />
          ) : pendingCount === 0 ? (
            <Empty
              message="Nothing waiting on you"
              hint="Orders queue here only in HUMAN_APPROVAL mode."
            />
          ) : (
            <ul className="divide-y divide-line/70">
              {pending!.pending.map((order) => (
                <li
                  key={order.order_id}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge tone={String(order.side).toUpperCase() === "BUY" ? "good" : "bad"}>
                        {String(order.side ?? "?")}
                      </Badge>
                      <span className="font-medium text-ink">{order.symbol ?? "—"}</span>
                      <span className="nums text-sm text-soft">
                        {order.quantity !== undefined ? num(Number(order.quantity), 2) : ""}
                      </span>
                    </div>
                    <div className="mt-0.5 font-mono text-2xs text-faint">
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
          )}
        </Card>
      )}

      {tab === "orders" && (
        <Card bodyClassName="">
          {ordersLoading ? (
            <Loading />
          ) : !orders?.orders.length ? (
            <Empty message="No orders yet" />
          ) : (
            <Table head={["Symbol", "Side", "Qty", "Type", "Status", "Broker", "Placed"]}>
              {orders.orders.map((order) => (
                <tr key={order.id} className="row-hover">
                  <td className="td">
                    <div className="font-medium">{order.symbol}</div>
                    <div className="text-2xs uppercase text-faint">{order.exchange}</div>
                  </td>
                  <td className="td text-right">
                    <Badge tone={order.side.toUpperCase() === "BUY" ? "good" : "bad"}>
                      {order.side}
                    </Badge>
                  </td>
                  <td className="td nums text-right">{num(order.quantity, 2)}</td>
                  <td className="td text-right text-xs uppercase text-soft">{order.order_type}</td>
                  <td className="td text-right">
                    <Badge tone={statusTone(order.status)}>{order.status}</Badge>
                    {order.rejection_reason && (
                      <div className="mt-0.5 max-w-[220px] truncate text-2xs text-down">
                        {order.rejection_reason}
                      </div>
                    )}
                  </td>
                  <td className="td text-right text-xs text-soft">{order.broker}</td>
                  <td className="td text-right text-xs text-soft">{dateTime(order.created_at)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}

      {tab === "fills" && (
        <Card bodyClassName="">
          {fillsLoading ? (
            <Loading />
          ) : !fills?.fills.length ? (
            <Empty message="No fills yet" />
          ) : (
            <Table head={["Symbol", "Side", "Qty", "Price", "Notional", "Slippage", "Filled"]}>
              {fills.fills.map((fill) => (
                <tr key={fill.id} className="row-hover">
                  <td className="td font-medium">{fill.symbol ?? "—"}</td>
                  <td className="td text-right">
                    {fill.side && (
                      <Badge tone={fill.side.toUpperCase() === "BUY" ? "good" : "bad"}>
                        {fill.side}
                      </Badge>
                    )}
                  </td>
                  <td className="td nums text-right">{num(fill.filled_qty, 4)}</td>
                  <td className="td nums text-right">{money(fill.fill_price)}</td>
                  <td className="td nums text-right">{money(fill.notional)}</td>
                  <td className="td nums text-right text-xs text-soft">
                    {num(fill.slippage, 4)}
                  </td>
                  <td className="td text-right text-xs text-soft">{dateTime(fill.filled_at)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </>
  );
}
