// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-FAA1D5316308
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { Radar, RefreshCw } from "lucide-react";
import { useState } from "react";

import { useCommand, useConfig, useSignals } from "@/lib/api";
import { dateTime, num } from "@/lib/format";
import {
  Badge,
  Card,
  CommandEcho,
  Empty,
  Loading,
  PageHeader,
  Table,
} from "@/components/ui";

function Toggle({
  on,
  onChange,
  disabled,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={clsx(
        "relative h-5 w-9 shrink-0 rounded-full transition disabled:opacity-50",
        on ? "bg-clay" : "bg-line",
      )}
    >
      <span
        className={clsx(
          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all",
          on ? "left-[18px]" : "left-0.5",
        )}
      />
    </button>
  );
}

/** Optional sleeves are UNVALIDATED and default off — the toggles run the same
 *  `sleeve`/`pm`/`crypto` commands, so the same guards and warnings apply. */
function SleevePanel({ onEcho }: { onEcho: (html: string, text: string) => void }) {
  const { data: config, isLoading } = useConfig();
  const command = useCommand();

  const run = (line: string) =>
    command.mutate(line, { onSuccess: (r) => onEcho(r.html, r.text) });

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
    <div className="space-y-3">
      {sleeves.map((sleeve) => (
        <div key={sleeve.key} className="rounded-lg border border-line px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ink">{sleeve.title}</span>
                <Badge tone="warn">unvalidated</Badge>
              </div>
              <p className="mt-0.5 text-xs text-soft">{sleeve.detail}</p>
            </div>
            <Toggle
              on={sleeve.state.enabled}
              disabled={command.isPending}
              onChange={(next) =>
                run(`sleeve ${next ? "on" : "off"} ${sleeve.key}`)
              }
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-soft">
            <span className="nums">
              weight {(sleeve.state.weight * 100).toFixed(0)}% of book
            </span>
            <label className="flex items-center gap-2">
              <span>auto-discovery</span>
              <Toggle
                on={sleeve.state.discovery}
                disabled={command.isPending}
                onChange={(next) =>
                  run(
                    next
                      ? `${sleeve.discoveryCommand} on ${sleeve.state.discovery_top_n}`
                      : `${sleeve.discoveryCommand} off`,
                  )
                }
              />
              <span className="nums text-faint">top {sleeve.state.discovery_top_n}</span>
            </label>
            <button
              onClick={() => run(sleeve.scanCommand)}
              disabled={command.isPending}
              className="btn btn-ghost text-xs"
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
  const { data, isLoading } = useSignals();
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

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Recent signals" bodyClassName="">
          {isLoading ? (
            <Loading />
          ) : signals.length === 0 ? (
            <Empty
              message="No signals yet"
              hint="Sleeves rebalance on their own cadence — weekly for the research stack."
            />
          ) : (
            <Table head={["Symbol", "Direction", "Strength", "Confidence", "Strategy", "When"]}>
              {signals.map((signal) => (
                <tr key={signal.signal_id} className="row-hover">
                  <td className="td font-medium">{signal.symbol}</td>
                  <td className="td text-right">
                    <Badge
                      tone={
                        signal.direction.toUpperCase() === "BUY"
                          ? "good"
                          : signal.direction.toUpperCase() === "SELL"
                            ? "bad"
                            : "neutral"
                      }
                    >
                      {signal.direction}
                    </Badge>
                  </td>
                  <td className="td nums text-right">{num(signal.strength, 3)}</td>
                  <td className="td nums text-right">{num(signal.confidence, 2)}</td>
                  <td className="td text-right text-xs text-soft">
                    {signal.strategy_name ?? signal.agent_id}
                    {signal.regime && (
                      <div className="text-2xs uppercase text-faint">{signal.regime}</div>
                    )}
                  </td>
                  <td className="td text-right text-xs text-soft">
                    {dateTime(signal.created_at)}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Optional sleeves" subtitle="Off by default; carved pro-rata from the validated mix">
          <SleevePanel onEcho={(html, text) => setEcho({ html, text })} />
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token FAA1D5316308 - verify with scripts/authorship.py verify
