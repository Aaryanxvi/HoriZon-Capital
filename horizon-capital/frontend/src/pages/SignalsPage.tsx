// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-FAA1D5316308
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Radar, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { useCommand, useConfig, useOverview, usePositions, useSignals } from "@/lib/api";
import { dateTime, num, timeAgo } from "@/lib/format";
import { useSleeves } from "@/lib/viz-api";
import { ChartCard, Dumbbell, HBarList, withSign } from "@/components/charts";
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
  hint: "Start the engine to see sleeve targets.",
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

function TargetsCard() {
  const sleevesQ = useSleeves();
  const positionsQ = usePositions();
  const overviewQ = useOverview();
  const sleeves = sleevesQ.data;
  const nav = overviewQ.data?.nav ?? 0;

  // Current weight per symbol = |market value| / NAV.
  const held = new Map<string, number>();
  for (const p of positionsQ.data?.positions ?? []) {
    const w = nav > 0 ? (Math.abs(p.market_value) / nav) * 100 : 0;
    held.set(bare(p.symbol), (held.get(bare(p.symbol)) ?? 0) + w);
  }

  const groups = (sleeves?.sleeves ?? []).map((sleeve) => ({
    sleeve,
    rows: [...sleeve.signals]
      .sort((a, b) => b.weight - a.weight)
      .map((sig) => ({
        key: sig.symbol,
        label: sig.symbol,
        current: held.get(bare(sig.symbol)) ?? 0,
        target: sig.weight * 100,
      })),
  }));
  // One scale across sleeves so a 2% gap looks the same in every group.
  const max = Math.max(0, ...groups.flatMap((g) => g.rows.flatMap((r) => [r.current, r.target])));
  const error = sleevesQ.error ?? positionsQ.error ?? overviewQ.error;

  return (
    <ChartCard
      title="Targets vs current weights"
      subtitle={
        sleeves?.market_open == null
          ? "% of NAV"
          : `% of NAV · US market ${sleeves.market_open ? "open" : "closed"}`
      }
      isLoading={sleevesQ.isLoading || positionsQ.isLoading || overviewQ.isLoading}
      isFetching={sleevesQ.isFetching}
      error={error ? `Could not load sleeve targets — ${error.message}` : null}
      empty={
        !sleeves?.available
          ? AGENT_DOWN
          : !groups.some((g) => g.rows.length)
            ? {
                message: "No targets yet",
                hint: "Sleeves fire during US market hours; `strategy tick` forces a cycle.",
              }
            : null
      }
      table={{
        columns: ["Sleeve", "Symbol", "Current", "Target", "Gap"],
        rows: groups.flatMap((g) =>
          g.rows.map((r) => [
            g.sleeve.name,
            r.label,
            pct1(r.current),
            pct1(r.target),
            withSign(r.target - r.current, pct1),
          ]),
        ),
      }}
    >
      <div className="space-y-4">
        {groups.map(({ sleeve, rows }) => (
          <section key={sleeve.name}>
            <h3 className="mb-1 flex items-baseline gap-2 px-1 text-2xs font-semibold uppercase tracking-wide text-ink-3">
              {sleeve.name}
              <span className="nums font-normal normal-case tracking-normal">
                {pct1(sleeve.weight * 100)} of book
              </span>
            </h3>
            {rows.length ? (
              <Dumbbell rows={rows} format={pct1} max={max} />
            ) : (
              <p className="px-1 text-xs text-ink-3">No targets yet</p>
            )}
          </section>
        ))}
      </div>
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
        subtitle="Strategy sleeve output — a signal only fires on >50bps drift from target weight"
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
          <TargetsCard />

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
