// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-BBE68EA80F1F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { ArrowUpRight } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ChartCard, HBarList, StatTile, type StatTileProps } from "@/components/charts";
import { MorningBrief } from "@/components/MorningBrief";
import { PortfolioVsBenchmark } from "@/components/PortfolioVsBenchmark";
import { RegimeGauge } from "@/components/RegimeGauge";
import {
  Badge,
  Card,
  Dot,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  StatusChip,
  type StatusChipTone,
} from "@/components/ui";
import {
  ApiError,
  useAlerts,
  useEquityCurve,
  useOverview,
  usePositions,
  useRisk,
  useWatchlist,
  type Overview,
} from "@/lib/api";
import { clock, money, timeAgo } from "@/lib/format";
import { describeEvent, useLiveStore } from "@/lib/live";
import { allocationRows, CASH_KEY } from "@/lib/portfolio";
import { useNavDaily } from "@/lib/viz-api";

/** Signed percent from a PERCENT number: 1.234 → "+1.23%", −0.5 → "−0.50%". */
const signedPct = (v: number, d = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}%`;
/** Drawdown magnitude (fraction) → "−1.23%". */
const ddText = (dd: number) => `${dd ? "−" : ""}${(Math.abs(dd) * 100).toFixed(2)}%`;
const weight = (v: number) => `${v.toFixed(1)}%`;

function failure(endpoint: string, e: unknown): string {
  const why = e instanceof ApiError ? `HTTP ${e.status}` : e instanceof Error ? e.message : "request failed";
  return `GET ${endpoint} failed (${why})`;
}

// Bullet thresholds (spec §5): ratio of value to limit.
function limitStatus(ratio: number): NonNullable<StatTileProps["status"]> {
  if (ratio >= 1) return { tone: "critical", label: "Breach" };
  if (ratio >= 0.85) return { tone: "serious", label: "Near limit" };
  if (ratio >= 0.6) return { tone: "warning", label: "Elevated" };
  return { tone: "ok", label: "OK" };
}

function severityTone(severity: string | null | undefined): StatusChipTone {
  const s = (severity ?? "").toUpperCase();
  if (s === "CRITICAL") return "critical";
  if (s === "HIGH" || s === "ERROR") return "serious";
  if (s === "WARNING" || s === "MEDIUM") return "warning";
  return "neutral";
}

function KpiRow({ data }: { data: Overview }) {
  const curve = useEquityCurve();
  const navDaily = useNavDaily();
  const risk = useRisk();

  const intraday = useMemo(() => (curve.data?.points ?? []).slice(-120).map((p) => p.total_value), [curve.data]);
  const dayTrend = useMemo(() => intraday.map((v) => v - intraday[0]), [intraday]);
  const dailyNavs = useMemo(() => (navDaily.data?.points ?? []).map((p) => p.nav), [navDaily.data]);

  // current_drawdown / max_drawdown are FRACTIONS; limits.*_pct are PERCENT.
  const latest = risk.data?.latest;
  const history = risk.data?.history ?? [];
  const dd = typeof latest?.current_drawdown === "number" ? Math.abs(latest.current_drawdown) : null;
  const maxDd = typeof latest?.max_drawdown === "number" ? latest.max_drawdown : null;
  const ddLimit = risk.data?.limits.max_drawdown_pct ?? null;
  const ddTrend = useMemo(() => history.map((h) => -Math.abs(h.current_drawdown)), [history]);

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile
        label="NAV"
        value={money(data.nav)}
        delta={{ value: data.day_pnl_pct, format: signedPct, label: "today" }}
        trend={intraday}
      />
      <StatTile
        label="Day P&L"
        value={`${data.day_pnl > 0 ? "+" : ""}${money(data.day_pnl)}`}
        delta={{ value: data.day_pnl_pct, format: signedPct }}
        trend={dayTrend}
      />
      <StatTile
        label="Total return"
        value={signedPct(data.total_return_pct)}
        hint={`from ${money(data.initial_capital)}`}
        trend={dailyNavs}
      />
      <StatTile
        label="Drawdown"
        value={dd === null ? "—" : ddText(dd)}
        status={dd !== null && ddLimit ? limitStatus((dd * 100) / ddLimit) : undefined}
        hint={
          risk.isLoading
            ? undefined
            : dd === null
              ? "No risk snapshot yet"
              : `max ${maxDd === null ? "—" : ddText(maxDd)}${ddLimit ? ` · limit ${ddLimit}%` : ""}`
        }
        trend={ddTrend}
      />
    </div>
  );
}

function ActivityFeed() {
  const events = useLiveStore((s) => s.events);
  const connected = useLiveStore((s) => s.connected);

  if (!events.length)
    return (
      <Empty
        message={connected ? "Waiting for the first event" : "Not connected"}
        hint={
          connected
            ? "Ticks, signals, orders and debates appear here as the agents publish them."
            : "The backend event stream is unavailable."
        }
      />
    );

  return (
    <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
      {events.slice(0, 60).map((event, i) => (
        <li key={i} className="flex items-center gap-2.5 px-3 py-1.5 text-sm">
          <span className="w-[60px] shrink-0 whitespace-nowrap font-mono text-2xs text-ink-3">
            {clock(event.timestamp)}
          </span>
          <Badge tone="accent" className="max-w-[104px] shrink-0">
            <span className="min-w-0 truncate">{event.type.replace(/_/g, " ")}</span>
          </Badge>
          <span className="min-w-0 flex-1 truncate text-ink-2">{describeEvent(event)}</span>
        </li>
      ))}
    </ul>
  );
}

function AllocationCard({ nav, cash }: { nav: number; cash: number }) {
  const navigate = useNavigate();
  const positions = usePositions();
  const risk = useRisk();
  const limit = risk.data?.limits.max_position_pct ?? null;
  const list = positions.data?.positions ?? [];
  // allocationRows is sorted desc by weight, so the first 10 non-cash rows are the top 10 by |value|.
  let shown = 0;
  const rows = allocationRows(list, nav, cash, limit).filter((r) => r.key === CASH_KEY || shown++ < 10);

  return (
    <ChartCard
      title="Allocation by position"
      subtitle={`% of NAV${limit !== null ? ` · limit ${limit}%` : ""}`}
      isLoading={positions.isLoading}
      isFetching={positions.isFetching && !positions.isLoading}
      error={positions.error ? failure("/api/desktop/positions", positions.error) : null}
      empty={
        rows.length
          ? null
          : { message: "No NAV to allocate yet", hint: "Weights appear once the portfolio agent writes its first snapshot." }
      }
    >
      <HBarList rows={rows} format={weight} maxRows={11} onRowClick={() => navigate("/portfolio")} />
      {list.length === 0 && (
        <p className="mt-2 text-xs text-ink-3">No open positions — signals become orders once the sleeves fire.</p>
      )}
      {list.length > 10 && <p className="mt-2 text-xs text-ink-3">Top 10 of {list.length} positions.</p>}
    </ChartCard>
  );
}

function WatchlistCard() {
  const { data, isLoading, error } = useWatchlist();
  return (
    <Card
      title="Watchlist"
      subtitle="Latest marks"
      action={
        <Link to="/watchlist" className="btn btn-ghost text-xs">
          Manage <ArrowUpRight className="h-3 w-3" />
        </Link>
      }
      bodyClassName=""
    >
      {isLoading ? (
        <Loading />
      ) : error ? (
        <div className="p-3">
          <ErrorNote message={failure("/api/desktop/watchlist", error)} />
        </div>
      ) : !data?.watchlist.length ? (
        <Empty message="No symbols priced yet" hint="Add symbols on the Watchlist screen." />
      ) : (
        <ul className="max-h-[280px] divide-y divide-line overflow-y-auto">
          {data.watchlist.map((w) => {
            const change = w.prev_close ? w.change_pct : null;
            return (
              <li key={w.symbol} className="flex items-center justify-between gap-3 px-3 py-1.5">
                <span className="truncate text-sm text-ink">{w.symbol}</span>
                <span className="flex items-center gap-3">
                  <span className="nums text-sm text-ink-2">{w.price ? money(w.price) : "—"}</span>
                  <span
                    className={`nums w-[72px] text-right text-xs ${
                      change === null || change === 0 ? "text-ink-3" : change > 0 ? "text-up" : "text-down"
                    }`}
                  >
                    {change === null ? "—" : `${change > 0 ? "▲ " : change < 0 ? "▼ " : ""}${signedPct(change)}`}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function AlertsCard() {
  const { data, isLoading, error } = useAlerts();
  return (
    <Card title="Alerts" subtitle="Most recent first" bodyClassName="">
      {isLoading ? (
        <Loading />
      ) : error ? (
        <div className="p-3">
          <ErrorNote message={failure("/api/desktop/alerts", error)} />
        </div>
      ) : !data?.alerts.length ? (
        <Empty message="No alerts" hint="Risk, health and compliance alerts land here." />
      ) : (
        <ul className="max-h-[280px] divide-y divide-line overflow-y-auto">
          {data.alerts.slice(0, 20).map((a) => (
            <li key={a.id} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-ink">{a.title}</span>
                <StatusChip tone={severityTone(a.severity)} label={a.severity || "info"} />
              </div>
              <div className="mt-0.5 truncate text-xs text-ink-2">{a.message}</div>
              <div className="mt-0.5 text-2xs text-ink-3">{timeAgo(a.created_at)}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function OverviewPage() {
  const { data, isLoading, error } = useOverview();

  if (isLoading) return <Loading label="Loading portfolio" />;
  if (error || !data)
    return (
      <ErrorNote
        message={`${error ? failure("/api/desktop/overview", error) : "No overview data"} — is the engine running?`}
      />
    );

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5">
              <Dot tone={data.agents_running > 0 ? "good" : "bad"} pulse={data.agents_running > 0} />
              {data.agents_running}/{data.agents_total} agents
            </span>
            <span className="text-ink-3">·</span>
            <span>{data.system_mode.replace(/_/g, " ").toLowerCase()}</span>
            {data.regime && (
              <>
                <span className="text-ink-3">·</span>
                <span>regime {data.regime.toLowerCase()}</span>
              </>
            )}
            {data.llm_providers.length > 0 && (
              <>
                <span className="text-ink-3">·</span>
                <span>llm {data.llm_providers.join(", ")}</span>
              </>
            )}
          </span>
        }
      />

      <div className="flex flex-col gap-3">
        {(data.halted || data.kill_switch) && (
          <ErrorNote
            message={
              data.kill_switch
                ? "Kill switch active — the execution agent is rejecting every new order."
                : `Trading halted${data.halt_reason ? `: ${data.halt_reason}` : "."}`
            }
          />
        )}

        <MorningBrief />

        <KpiRow data={data} />

        <div className="grid gap-3 lg:grid-cols-3">
          <PortfolioVsBenchmark className="lg:col-span-2" syncKey="overview" />
          <Card title="Live activity" subtitle="Straight off the agent bus" bodyClassName="">
            <ActivityFeed />
          </Card>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <AllocationCard nav={data.nav} cash={data.cash_usd} />
          <RegimeGauge />
          <div className="flex flex-col gap-3">
            <WatchlistCard />
            <AlertsCard />
          </div>
        </div>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token BBE68EA80F1F - verify with scripts/authorship.py verify
