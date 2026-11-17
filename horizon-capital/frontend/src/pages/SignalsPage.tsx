// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-FAA1D5316308
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { Radar, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { useCommand, useConfig, useOverview, usePositions, useSignals } from "@/lib/api";
import { compactMoney, dateTime, num, timeAgo } from "@/lib/format";
import { useSleeves } from "@/lib/viz-api";
import { ChartCard, HBarList } from "@/components/charts";
import {
  Badge,
  Card,
  CommandEcho,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Table,
  Toggle,
} from "@/components/ui";

const pct1 = (v: number) => `${v.toFixed(1)}%`;

// ponytail: positions may carry an exchange suffix (SPY.NYSE) that signals don't, so match on the
// part before the first dot; share classes like BRK.A/BRK.B would collide — key on exchange if held.
const bare = (symbol: string) => symbol.toUpperCase().split(".")[0];

const AGENT_DOWN = {
  message: "Strategy agent not running",
  hint: "Start the engine to see the AI's trade ideas.",
};

/** Direction is up/down colour, so it always travels with its glyph. */
function DirectionChip({ direction }: { direction: string }) {
  const d = direction.toUpperCase();
  if (d !== "BUY" && d !== "SELL") return <Badge>{direction}</Badge>;
  const up = d === "BUY";
  return (
    <Badge
      className={up ? "!border-up/30 !bg-up/10" : "!border-down/30 !bg-down/10"}
      icon={
        <span aria-hidden className={up ? "text-up" : "text-down"}>
          {up ? "▲" : "▼"}
        </span>
      }
    >
      {direction}
    </Badge>
  );
}

/** Plain-English names for the strategy sleeves. */
const STRATEGY_LABEL: Record<string, string> = {
  research_stack: "Research Stack strategy (market regime + momentum + quality)",
  trend_filter: "Trend Filter strategy (follows the 200-day trend)",
  gap_fade: "Gap Fade strategy (buys sharp overnight dips)",
  momentum_rank: "Momentum strategy (owns the strongest performers)",
  dual_momentum: "Dual Momentum strategy",
  breadth_alpha: "Market Breadth strategy",
  crypto_trend: "Crypto Trend strategy",
  polymarket_momentum: "Prediction-market strategy",
};

const strategyLabel = (name: string) =>
  STRATEGY_LABEL[name] ?? `${name.replace(/_/g, " ")} strategy`;

/** Gaps smaller than this (percent of the fund) count as "already the right size". */
const MIN_GAP_PCT = 0.5;

/**
 * Why the AI wants to trade, in plain English: for each stock a strategy wants
 * to own, compare how much of the fund it should be with how much it is today,
 * and say what the AI proposes to do about the difference.
 */
function TradeIdeasCard() {
  const sleevesQ = useSleeves();
  const positionsQ = usePositions();
  const overviewQ = useOverview();
  const sleeves = sleevesQ.data;
  const nav = overviewQ.data?.nav ?? 0;

  // How much of the fund each symbol is today, in percent.
  const held = new Map<string, number>();
  for (const p of positionsQ.data?.positions ?? []) {
    const w = nav > 0 ? (Math.abs(p.market_value) / nav) * 100 : 0;
    held.set(bare(p.symbol), (held.get(bare(p.symbol)) ?? 0) + w);
  }

  const ideas = (sleeves?.sleeves ?? []).flatMap((sleeve) =>
    sleeve.signals.map((sig) => {
      const wantPct = sig.weight * 100;
      const havePct = held.get(bare(sig.symbol)) ?? 0;
      return {
        sleeve: sleeve.name,
        symbol: bare(sig.symbol),
        wantPct,
        havePct,
        gapPct: wantPct - havePct,
      };
    }),
  );
  const actionable = ideas
    .filter((i) => Math.abs(i.gapPct) >= MIN_GAP_PCT)
    .sort((a, b) => Math.abs(b.gapPct) - Math.abs(a.gapPct));
  const onTarget = ideas.length - actionable.length;
  const amountOf = (gapPct: number) => compactMoney((Math.abs(gapPct) / 100) * nav);
  const error = sleevesQ.error ?? positionsQ.error ?? overviewQ.error;

  return (
    <ChartCard
      title="Why the AI wants to trade"
      subtitle={
        "Each strategy decides how much of the fund a stock deserves" +
        (sleeves?.market_open == null
          ? ""
          : ` · US market ${sleeves.market_open ? "open" : "closed"}`)
      }
      isLoading={sleevesQ.isLoading || positionsQ.isLoading || overviewQ.isLoading}
      isFetching={sleevesQ.isFetching}
      error={error ? `Could not load trade ideas — ${error.message}` : null}
      empty={
        !sleeves?.available
          ? AGENT_DOWN
          : !ideas.length
            ? { message: "No trade ideas yet", hint: "The strategies run during US market hours." }
            : null
      }
      table={{
        columns: ["Stock", "Strategy", "Should be", "Is today", "AI proposes"],
        rows: actionable.map((i) => [
          i.symbol,
          strategyLabel(i.sleeve),
          pct1(i.wantPct),
          pct1(i.havePct),
          `${i.gapPct > 0 ? "Buy" : "Sell"} ${amountOf(i.gapPct)}`,
        ]),
      }}
    >
      {actionable.length === 0 ? (
        <p className="px-1 py-2 text-sm text-ink-2">
          Every holding is already the size its strategy wants. Nothing to trade right now.
        </p>
      ) : (
        <ul className="space-y-2">
          {actionable.slice(0, 6).map((i) => {
            const buy = i.gapPct > 0;
            return (
              <li
                key={`${i.sleeve}-${i.symbol}`}
                className="flex items-start gap-3 rounded border border-line px-3 py-2.5"
              >
                <span
                  className={clsx(
                    "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-2xs font-semibold uppercase",
                    buy ? "bg-up/10 text-up" : "bg-down/10 text-down",
                  )}
                >
                  {buy ? "Buy" : "Sell"}
                </span>
                <p className="text-sm leading-relaxed text-ink-2">
                  The {strategyLabel(i.sleeve)} wants{" "}
                  <span className="font-semibold text-ink">{i.symbol}</span> to be{" "}
                  <span className="nums font-medium text-ink">{pct1(i.wantPct)}</span> of the fund.
                  It is <span className="nums font-medium text-ink">{pct1(i.havePct)}</span> today,
                  so the AI proposes to {buy ? "buy" : "sell"} about{" "}
                  <span className="nums font-medium text-ink">{amountOf(i.gapPct)}</span>. The AI
                  debate reviews it before any order is placed.
                </p>
              </li>
            );
          })}
          {actionable.length > 6 && (
            <li className="px-1 text-xs text-ink-3">
              +{actionable.length - 6} more. Switch to the table view to see them all.
            </li>
          )}
        </ul>
      )}
      {onTarget > 0 && (
        <p className="mt-3 px-1 text-xs text-ink-3">
          {onTarget} other holding{onTarget === 1 ? " is" : "s are"} already the right size.
        </p>
      )}
    </ChartCard>
  );
}

function SleeveMixCard() {
  const { data, isLoading, isFetching, error } = useSleeves();
  const sleeves = [...(data?.sleeves ?? [])].sort((a, b) => b.weight - a.weight);

  return (
    <ChartCard
      title="Sleeve mix"
      subtitle="target weight"
      isLoading={isLoading}
      isFetching={isFetching}
      error={error ? `Could not load sleeves — ${error.message}` : null}
      empty={
        !data?.available
          ? AGENT_DOWN
          : !sleeves.length
            ? { message: "No sleeves configured", hint: "The strategy agent is running without sleeves." }
            : null
      }
      table={{
        columns: ["Sleeve", "Weight", "Cadence", "Last refresh", "Signals"],
        rows: sleeves.map((s) => [
          s.name,
          pct1(s.weight * 100),
          `every ${s.cadence_days}d`,
          s.last_refresh ? timeAgo(s.last_refresh) : "not yet",
          s.signals.length,
        ]),
      }}
    >
      <HBarList
        rows={sleeves.map((s) => ({
          key: s.name,
          label: s.name,
          sublabel: `every ${s.cadence_days}d · ${
            s.last_refresh ? `refreshed ${timeAgo(s.last_refresh)}` : "not yet refreshed"
          }`,
          value: s.weight * 100,
        }))}
        format={pct1}
      />
    </ChartCard>
  );
}

/** Optional sleeves are UNVALIDATED and default off — the toggles run the same
 *  `sleeve`/`pm`/`crypto` commands, so the same guards and warnings apply. */
function SleevePanel({ onEcho }: { onEcho: (html: string, text: string) => void }) {
  const { data: config, isLoading, error } = useConfig();
  const command = useCommand();

  const run = (line: string) =>
    command.mutate(line, { onSuccess: (r) => onEcho(r.html, r.text) });

  if (error)
    return (
      <div className="p-3">
        <ErrorNote message={`Could not load config — ${error.message}`} />
      </div>
    );
  if (isLoading || !config) return <Loading label="Loading sleeves" />;

  const sleeves = [
    {
      key: "crypto",
      title: "Crypto trend",
      detail: "Faber 200d SMA + vol damper",
      state: config.sleeves.crypto,
      discoveryCommand: "crypto auto",
      scanCommand: "crypto scan",
    },
    {
      key: "polymarket",
      title: "Polymarket momentum",
      detail: "7d probability momentum, tails filtered",
      state: config.sleeves.polymarket,
      discoveryCommand: "pm auto",
      scanCommand: "pm scan",
    },
  ];

  return (
    <div className="divide-y divide-line">
      {sleeves.map((sleeve) => (
        <div key={sleeve.key} className="px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ink">{sleeve.title}</span>
                <Badge tone="warn" icon={<TriangleAlert className="h-3 w-3 text-warn" aria-hidden />}>
                  unvalidated
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-ink-3">{sleeve.detail}</p>
            </div>
            <Toggle
              on={sleeve.state.enabled}
              disabled={command.isPending}
              label={`${sleeve.title} sleeve`}
              onChange={(next) =>
                run(`sleeve ${next ? "on" : "off"} ${sleeve.key}`)
              }
            />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-2">
            <span className="nums">
              weight {(sleeve.state.weight * 100).toFixed(0)}% of book
            </span>
            <label className="flex items-center gap-2">
              <span>auto-discovery</span>
              <Toggle
                on={sleeve.state.discovery}
                disabled={command.isPending}
                label={`${sleeve.title} auto-discovery`}
                onChange={(next) =>
                  run(
                    next
                      ? `${sleeve.discoveryCommand} on ${sleeve.state.discovery_top_n}`
                      : `${sleeve.discoveryCommand} off`,
                  )
                }
              />
              <span className="nums text-ink-3">top {sleeve.state.discovery_top_n}</span>
            </label>
            <button
              onClick={() => run(sleeve.scanCommand)}
              disabled={command.isPending}
              className="btn btn-ghost h-6 px-2 text-xs"
            >
              <RefreshCw className="h-3 w-3" /> Scan universe
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function SignalsPage() {
  const { data, isLoading, error } = useSignals();
  const [echo, setEcho] = useState<{ html: string; text: string } | null>(null);
  const command = useCommand();

  const signals = data?.signals ?? [];

  return (
    <>
      <PageHeader
        title="Signals"
        subtitle="Trade ideas from the AI strategies, and the reason behind each one"
        actions={
          <button
            className="btn"
            disabled={command.isPending}
            onClick={() =>
              command.mutate("strategy status", {
                onSuccess: (r) => setEcho({ html: r.html, text: r.text }),
              })
            }
          >
            <Radar className="h-3.5 w-3.5" /> Sleeve diagnostics
          </button>
        }
      />

      {echo && (
        <div className="mb-4">
          <CommandEcho html={echo.html} text={echo.text} onDismiss={() => setEcho(null)} />
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-3 lg:col-span-2">
          <TradeIdeasCard />

          <Card
            title="Recent signals"
            subtitle={signals.length ? `last ${signals.length}` : undefined}
            bodyClassName=""
          >
            {isLoading ? (
              <Loading />
            ) : error ? (
              <div className="p-3">
                <ErrorNote message={`Could not load signals — ${error.message}`} />
              </div>
            ) : signals.length === 0 ? (
              <Empty
                message="No signals yet"
                hint="Sleeves rebalance on their own cadence — weekly for the research stack."
              />
            ) : (
              <Table
                className="max-h-[480px]"
                head={["Symbol", "Direction", "Strength", "Confidence", "Strategy", "Regime", "When"]}
                align={["left", "left", "right", "right", "left", "left", "right"]}
              >
                {signals.map((signal) => (
                  <tr key={signal.signal_id} className="row-hover">
                    <td className="td font-medium">{signal.symbol}</td>
                    <td className="td">
                      <DirectionChip direction={signal.direction} />
                    </td>
                    <td className="td text-right">
                      <span className="inline-flex items-center gap-2">
                        <span className="nums text-xs text-ink">{num(signal.strength, 3)}</span>
                        <span className="h-1 w-14 overflow-hidden rounded-full bg-line" aria-hidden>
                          <span
                            className="block h-full rounded-full bg-accent"
                            style={{ width: `${Math.min(Math.max(signal.strength, 0), 1) * 100}%` }}
                          />
                        </span>
                      </span>
                    </td>
                    <td className="td nums text-right">{num(signal.confidence, 2)}</td>
                    <td className="td text-xs text-ink-2">{signal.strategy_name ?? signal.agent_id}</td>
                    <td className="td text-2xs uppercase text-ink-3">{signal.regime ?? "—"}</td>
                    <td className="td nums text-right text-xs text-ink-2">
                      {dateTime(signal.created_at)}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <SleeveMixCard />

          <Card
            title="Optional sleeves"
            subtitle="Off by default; carved pro-rata from the validated mix"
            bodyClassName=""
          >
            <SleevePanel onEcho={(html, text) => setEcho({ html, text })} />
          </Card>
        </div>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token FAA1D5316308 - verify with scripts/authorship.py verify
