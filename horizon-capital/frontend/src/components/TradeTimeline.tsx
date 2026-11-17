import { ArrowUpRight, Check, Minus, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge, ErrorNote, Loading, StatusChip, statusTone, type StatusChipTone } from "@/components/ui";
import { dateTime, money, num, pct, tone } from "@/lib/format";
import { useTradeTimeline, type StepKey, type TimelineStep } from "@/lib/trades-api";

const TITLE: Record<StepKey, string> = {
  signal: "Signal",
  risk: "Risk check",
  debate: "Debate",
  order: "Order",
  fill: "Fill",
  pnl: "P&L since",
};

const CHIP: Record<string, StatusChipTone> = { good: "ok", bad: "critical", warn: "warning", neutral: "neutral" };

// Rail marker per step status. Skipped/unknown stay muted so they never read as a pass.
const MARK: Record<TimelineStep["status"], { cls: string; icon: ReactNode; label: string }> = {
  done: { cls: "border-ok/40 bg-ok/10 text-ok", icon: <Check className="h-3 w-3" />, label: "Done" },
  blocked: { cls: "border-crit/40 bg-crit/10 text-crit", icon: <X className="h-3 w-3" />, label: "Blocked" },
  skipped: { cls: "border-dashed border-line-strong bg-surface text-ink-3", icon: <Minus className="h-3 w-3" />, label: "Skipped" },
  unknown: {
    cls: "border-dashed border-warn/50 bg-surface text-warn",
    icon: <span className="text-2xs font-semibold leading-none">?</span>,
    label: "Not recorded",
  },
};

const ms = (iso: string) => new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();

function span(seconds: number): string {
  const s = Math.abs(seconds);
  if (s < 10) return `${s.toFixed(1)}s`;
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86_400)}d ${Math.floor((s % 86_400) / 3600)}h`;
}

const qty = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : "—");

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-3">{label}</dt>
      <dd className="nums min-w-0 break-words text-ink">{children}</dd>
    </>
  );
}

function Details({ step }: { step: TimelineStep }) {
  const d = step.detail;
  switch (step.key) {
    case "signal":
      return (
        <>
          <Row label="Strategy">{d.strategy ?? "—"}</Row>
          <Row label="Direction">{d.direction ?? "—"}</Row>
          <Row label="Strength">{num(d.strength, 3)}</Row>
          {d.confidence != null && <Row label="Confidence">{num(d.confidence, 3)}</Row>}
          {d.target_weight != null && <Row label="Target weight">{num(d.target_weight * 100, 2)}%</Row>}
          {d.regime && <Row label="Regime">{d.regime}</Row>}
          {d.reasoning && <Row label="Why">{d.reasoning}</Row>}
        </>
      );
    case "risk":
      return (
        <>
          <Row label="Decision">{d.decision}</Row>
          {d.violations?.length > 0 && <Row label="Violations">{d.violations.join("; ")}</Row>}
        </>
      );
    case "debate": {
      const votes = Object.entries((d.votes ?? {}) as Record<string, number>)
        .map(([v, n]) => `${n} ${v.toLowerCase()}`)
        .join(" · ");
      return (
        <>
          <Row label="Outcome">
            <StatusChip tone={CHIP[statusTone(d.decision)]} label={d.decision ?? "—"} />
          </Row>
          <Row label="Consensus">{num(d.consensus, 2)}</Row>
          <Row label="Votes">{votes || "none recorded"}</Row>
          {d.rounds != null && <Row label="Rounds">{d.rounds}</Row>}
          {d.reason && (
            <Row label="Reason">
              <span className="line-clamp-3" title={d.reason}>
                {d.reason}
              </span>
            </Row>
          )}
          <Row label="Session">
            <Link to={`/debates?session=${d.session_id}`} className="inline-flex items-center gap-0.5 text-accent hover:underline">
              Open in Debates <ArrowUpRight className="h-3 w-3" />
            </Link>
          </Row>
        </>
      );
    }
    case "order":
      return (
        <>
          <Row label="Ticket">
            {d.side} {qty(d.quantity)} · {d.order_type}
            {d.limit_price != null && ` @ ${money(d.limit_price)}`}
          </Row>
          <Row label="Status">
            <StatusChip tone={CHIP[statusTone(d.status)]} label={d.status} />
          </Row>
          {d.rejection_reason && (
            <Row label="Reason">
              <span className="text-crit">{d.rejection_reason}</span>
            </Row>
          )}
          <Row label="Broker">
            {d.broker} · {d.mode}
          </Row>
          {d.strategy && <Row label="Source">{d.strategy}</Row>}
          {d.broker_order_id && (
            <Row label="Broker id">
              <span className="font-mono text-2xs text-ink-2">{d.broker_order_id}</span>
            </Row>
          )}
        </>
      );
    case "fill":
      return (
        <>
          <Row label="Filled">
            {qty(d.filled_qty)} @ {money(d.avg_price)}
            {d.fills?.length > 1 && <span className="text-ink-3"> avg of {d.fills.length} fills</span>}
          </Row>
          <Row label="Slippage">
            {d.slippage_bps != null ? (
              <>
                <span className={tone(-d.slippage_bps)}>{num(d.slippage_bps, 1)} bps</span>
                <span className="text-ink-3">
                  {" "}
                  vs {d.ref_kind} price {money(d.ref_price)}
                </span>
              </>
            ) : (
              <span className="text-ink-3">not derivable (no sizing price recorded)</span>
            )}
          </Row>
          <Row label="Commission">{money(d.commission)}</Row>
        </>
      );
    case "pnl":
      return (
        <>
          <Row label="Mark">{money(d.mark)}</Row>
          <Row label={d.basis === "vs holding" ? "vs holding" : "Unrealised"}>
            <span className={tone(d.pnl)}>
              {money(d.pnl)} ({pct(d.pnl_pct)})
            </span>
          </Row>
          <Row label="Realised">
            <span className="text-ink-3">not tracked per order</span>
          </Row>
        </>
      );
  }
}

function Step({ step, prevAt, last }: { step: TimelineStep; prevAt: string | null; last: boolean }) {
  const mark = MARK[step.status];
  const delta = step.at && prevAt ? (ms(step.at) - ms(prevAt)) / 1000 : null;
  const muted = step.status === "skipped" || step.status === "unknown";
  return (
    <li className="relative flex gap-3 pb-4">
      {!last && <span aria-hidden className="absolute left-[11px] top-6 bottom-0 w-px bg-line" />}
      <span
        aria-hidden
        className={`relative z-[1] mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${mark.cls}`}
      >
        {mark.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <h3 className={`text-sm font-semibold ${muted ? "text-ink-2" : "text-ink"}`}>{TITLE[step.key]}</h3>
          <span className="sr-only">{mark.label}</span>
          {muted && <span className="text-2xs uppercase tracking-wide text-ink-3">{mark.label}</span>}
          {step.link === "time" && (
            <Badge tone="warn" className="normal-case">
              matched by time
            </Badge>
          )}
          {step.at && (
            <span className="nums ml-auto text-2xs text-ink-3">
              {step.key === "pnl" ? "mark " : ""}
              {dateTime(step.at)}
              {delta != null && (
                <span className="ml-1.5 text-ink-2" title="Time since the previous recorded step">
                  {delta >= 0 ? `+${span(delta)}` : `${span(delta)} earlier`}
                </span>
              )}
            </span>
          )}
        </div>
        {step.note && <p className="mt-0.5 text-xs text-ink-3">{step.note}</p>}
        {Object.keys(step.detail).length > 0 && (
          <dl className="mt-1.5 grid grid-cols-[96px_1fr] gap-x-3 gap-y-1 text-xs">
            <Details step={step} />
          </dl>
        )}
      </div>
    </li>
  );
}

/** Right-hand drawer: one order's life, signal → risk → debate → order → fill → P&L. */
export default function TradeTimeline({ orderId, onClose }: { orderId: string; onClose: () => void }) {
  const q = useTradeTimeline(orderId);
  const closeRef = useRef<HTMLButtonElement>(null);
  const t = q.data;

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  let prevAt: string | null = null;
  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal aria-labelledby="trade-timeline-title">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <aside className="flex h-full w-full max-w-[520px] flex-col overflow-y-auto border-l border-line bg-surface shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 id="trade-timeline-title" className="truncate text-base font-semibold text-ink">
              {t ? `${t.side} ${t.symbol}` : "Trade timeline"}
            </h2>
            <p className="truncate font-mono text-2xs text-ink-3">{orderId}</p>
          </div>
          <div className="flex items-center gap-2">
            {t && <StatusChip tone={CHIP[statusTone(t.status)]} label={t.status} />}
            <button ref={closeRef} onClick={onClose} className="btn btn-ghost px-1.5" title="Close (Esc)" aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>
        <div className="p-4">
          {q.isLoading ? (
            <Loading />
          ) : q.error ? (
            <ErrorNote message={`Could not load this trade — ${q.error.message}`} />
          ) : (
            <ol>
              {t!.steps.map((step, i) => {
                const prev = prevAt;
                if (step.at) prevAt = step.at;
                return <Step key={step.key} step={step} prevAt={prev} last={i === t!.steps.length - 1} />;
              })}
            </ol>
          )}
        </div>
      </aside>
    </div>
  );
}
