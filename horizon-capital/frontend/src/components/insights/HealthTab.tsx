import { StatTile } from "@/components/charts";
import { Card, Empty, StatusChip, Table } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useHealthInsights, type HealthInsights } from "@/lib/insights-api";
import { age, NumCell, TabFrame } from "./shared";

const HEARTBEAT_STALE_S = 60; // agents beat every 10 s
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

export function HealthTab() {
  return (
    <TabFrame q={useHealthInsights()} label="health">
      {(d) => <HealthBody d={d} />}
    </TabFrame>
  );
}

function Fresh({ ageS, staleAfter }: { ageS: number | null; staleAfter: number }) {
  if (ageS === null) return <StatusChip tone="neutral" label="never" />;
  return ageS <= staleAfter ? (
    <StatusChip tone="ok" label="fresh" />
  ) : (
    <StatusChip tone="serious" label={`stale ${age(ageS)}`} />
  );
}

function HealthBody({ d }: { d: HealthInsights }) {
  const stalest = [...d.feeds]
    .filter((f) => f.age_s !== null)
    .sort((a, b) => b.age_s! / b.stale_after_s - a.age_s! / a.stale_after_s)[0];
  const staleCount = d.feeds.filter((f) => f.age_s === null || f.age_s > f.stale_after_s).length;
  const unacked = SEVERITIES.filter((s) => d.unacked_alerts[s]);
  const urgent = (d.unacked_alerts.CRITICAL?.count ?? 0) + (d.unacked_alerts.HIGH?.count ?? 0);
  const lastFailure = d.llm.failures[0];
  const restarts = d.agents.reduce((n, a) => n + (a.restarts ?? 0), 0);

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Engine"
          value={d.engine.running ? "Running" : "Off"}
          hint={`${d.engine.mode}${d.engine.halted ? " · halted" : ""}${d.engine.kill_switch ? " · kill switch" : ""}`}
          status={
            d.engine.kill_switch || d.engine.halted
              ? { tone: "critical", label: d.engine.kill_switch ? "Kill switch" : "Halted" }
              : d.engine.running
                ? { tone: "ok", label: "Live" }
                : { tone: "warning", label: "Not trading" }
          }
        />
        <StatTile
          label="Data feeds"
          value={`${d.feeds.length - staleCount} of ${d.feeds.length} fresh`}
          hint={stalest ? `stalest: ${stalest.name}, ${age(stalest.age_s)} old` : "no data recorded"}
          status={staleCount ? { tone: "serious", label: `${staleCount} stale` } : { tone: "ok", label: "Fresh" }}
        />
        <StatTile
          label="Unacknowledged alerts"
          value={String(unacked.reduce((n, s) => n + d.unacked_alerts[s].count, 0))}
          hint={unacked.map((s) => `${d.unacked_alerts[s].count} ${s.toLowerCase()}`).join(" · ") || "none"}
          status={urgent ? { tone: "critical", label: `${urgent} high+` } : undefined}
        />
        <StatTile
          label="LLM provider failures"
          value={String(d.llm.failures.length)}
          hint={
            lastFailure
              ? `last: ${lastFailure.provider ?? "?"} ${lastFailure.error ?? ""}, ${dateTime(lastFailure.at)}`
              : "none recorded"
          }
          status={lastFailure && !lastFailure.acknowledged ? { tone: "serious", label: "Unacknowledged" } : undefined}
        />
      </div>

      {!d.engine.running && (
        <p className="text-xs text-ink-3">
          The engine is off, so nothing below updates: feeds, heartbeats and snapshots show the last thing written
          before it stopped. Agent statuses are as last recorded, not live.
        </p>
      )}

      <div className="grid gap-3 xl:grid-cols-2">
        <Card title="Feed freshness" subtitle="Newest row per feed vs now" bodyClassName="p-0">
          <Table head={["Feed", "Last", "Age", "Expected within", "Status"]}>
            {d.feeds.map((f) => (
              <tr key={f.name}>
                <td className="td text-sm text-ink">{f.name}</td>
                <NumCell>{dateTime(f.last)}</NumCell>
                <NumCell>{age(f.age_s)}</NumCell>
                <NumCell>{age(f.stale_after_s)}</NumCell>
                <td className="td text-right">
                  <Fresh ageS={f.age_s} staleAfter={f.stale_after_s} />
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="LLM providers" subtitle={`Registered here: ${d.llm.configured.join(", ") || "none"}`} bodyClassName="p-0">
          {d.llm.failures.length ? (
            <Table head={["Provider", "Error", "When", "Acked"]} align={["left", "left", "right", "right"]}>
              {d.llm.failures.map((f) => (
                <tr key={f.at} title={f.message}>
                  <td className="td text-sm text-ink">{f.provider ?? "?"}</td>
                  <td className="td text-xs text-ink-2">{f.error ?? "—"}</td>
                  <NumCell>{dateTime(f.at)}</NumCell>
                  <td className="td text-right">
                    <StatusChip tone={f.acknowledged ? "neutral" : "serious"} label={f.acknowledged ? "yes" : "no"} />
                  </td>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty message="No provider failures recorded" />
          )}
          {Object.keys(d.llm.last_logged_call).length > 0 && (
            <p className="border-t border-line px-3 py-2 text-2xs text-ink-3">
              Last logged successful call:{" "}
              {Object.entries(d.llm.last_logged_call)
                .map(([p, at]) => `${p} ${dateTime(at)}`)
                .join(" · ")}
            </p>
          )}
        </Card>

        <Card
          title="Agents"
          subtitle={d.agents_live ? `Live from the orchestrator · ${restarts} restarts` : "As last recorded — restarts are only known while running"}
          bodyClassName="p-0"
        >
          {d.agents.length ? (
            <Table head={["Agent", "Status", "Heartbeat", "Restarts"]} align={["left", "left", "right", "right"]}>
              {d.agents.map((a) => (
                <tr key={a.agent_id} title={a.error ?? undefined}>
                  <td className="td text-sm text-ink">{a.agent_id}</td>
                  <td className="td text-xs text-ink-2">{d.agents_live ? a.status : `${a.status} (recorded)`}</td>
                  <td className="td text-right">
                    <Fresh ageS={a.age_s} staleAfter={HEARTBEAT_STALE_S} />
                  </td>
                  <NumCell why="only known while the engine runs">{a.restarts === null ? "—" : a.restarts}</NumCell>
                </tr>
              ))}
            </Table>
          ) : (
            <Empty message="No agents recorded" />
          )}
          {d.workers.length > 0 && (
            <p className="border-t border-line px-3 py-2 text-2xs text-ink-3">
              Workers: {d.workers.map((w) => `${w.name} ${w.status.toLowerCase()} (${w.restarts} restarts)`).join(" · ")}
            </p>
          )}
        </Card>

        <Card title="Price history per symbol" subtitle="Held positions first" bodyClassName="max-h-96 overflow-y-auto p-0">
          <Table head={["Symbol", "Last daily bar", "Last intraday bar"]}>
            {d.symbols.map((s) => (
              <tr key={s.symbol}>
                <td className="td text-sm text-ink">
                  {s.symbol}
                  {s.held && <span className="ml-1 text-2xs text-ink-3">held</span>}
                </td>
                <NumCell why="no daily bars — vol, beta and liquidity can't be modelled">
                  {s.last_daily ? `${s.last_daily.slice(0, 10)} (${age(s.daily_age_s)})` : "—"}
                </NumCell>
                <NumCell>{s.last_intraday ? `${dateTime(s.last_intraday)} (${age(s.intraday_age_s)})` : "—"}</NumCell>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
