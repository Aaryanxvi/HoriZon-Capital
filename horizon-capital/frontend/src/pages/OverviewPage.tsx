// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-BBE68EA80F1F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { ArrowUpRight, CircleDollarSign, Layers, TrendingUp, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  useAlerts,
  useEquityCurve,
  useOverview,
  usePositions,
  useWatchlist,
} from "@/lib/api";
import { tooltipStyle, useChartColors } from "@/lib/colors";
import { axisMoney, clock, money, pct, timeAgo, tone } from "@/lib/format";
import { describeEvent, useLiveStore } from "@/lib/live";
import {
  Badge,
  Card,
  Dot,
  Empty,
  ErrorNote,
  Loading,
  PageHeader,
  Stat,
} from "@/components/ui";

function EquityChart() {
  const { data, isLoading } = useEquityCurve();
  const colors = useChartColors();
  const points = (data?.points ?? []).map((p) => ({
    t: p.created_at,
    value: p.total_value,
  }));

  if (isLoading) return <Loading label="Loading equity curve" />;
  if (points.length < 2)
    return (
      <Empty
        message="Not enough history yet"
        hint="The portfolio agent writes a snapshot every minute; the curve appears once two exist."
      />
    );

  const first = points[0].value;
  const last = points[points.length - 1].value;
  const up = last >= first;
  const values = points.map((p) => p.value);
  const [min, max] = [Math.min(...values), Math.max(...values)];

  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={up ? colors.up : colors.down} stopOpacity={0.22} />
              <stop offset="100%" stopColor={up ? colors.up : colors.down} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="t" hide />
          <YAxis
            domain={["dataMin", "dataMax"]}
            width={62}
            tick={{ fontSize: 11, fill: colors.faint }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => axisMoney(v, min, max)}
          />
          <Tooltip
            contentStyle={tooltipStyle(colors)}
            labelFormatter={(label: string) => clock(label)}
            formatter={(value: number) => [money(value), "NAV"]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={up ? colors.up : colors.down}
            strokeWidth={1.75}
            fill="url(#equityFill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
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
    <ul className="max-h-[356px] divide-y divide-line/70 overflow-y-auto">
      {events.slice(0, 60).map((event, i) => (
        <li key={i} className="flex items-start gap-2.5 px-4 py-2 text-sm">
          <span className="nums w-16 shrink-0 whitespace-nowrap pt-0.5 text-2xs text-faint">
            {clock(event.timestamp)}
          </span>
          <span className="w-[92px] shrink-0 truncate text-2xs font-semibold uppercase tracking-wide text-clay">
            {event.type.toLowerCase()}
          </span>
          <span className="min-w-0 flex-1 truncate text-soft">{describeEvent(event)}</span>
        </li>
      ))}
    </ul>
  );
}

export default function OverviewPage() {
  const { data, isLoading, error } = useOverview();
  const { data: positions } = usePositions();
  const { data: watchlist } = useWatchlist();
  const { data: alerts } = useAlerts();

  if (isLoading) return <Loading label="Loading portfolio" />;
  if (error || !data)
    return <ErrorNote message="Could not reach the backend. Is the engine running?" />;

  const top = [...(positions?.positions ?? [])]
    .sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value))
    .slice(0, 6);

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
            <span className="text-faint">·</span>
            <span>{data.system_mode.replace(/_/g, " ").toLowerCase()}</span>
            {data.regime && (
              <>
                <span className="text-faint">·</span>
                <span>regime {data.regime.toLowerCase()}</span>
              </>
            )}
            {data.llm_providers.length > 0 && (
              <>
                <span className="text-faint">·</span>
                <span>llm {data.llm_providers.join(", ")}</span>
              </>
            )}
          </span>
        }
      />

      {(data.halted || data.kill_switch) && (
        <div className="mb-5">
          <ErrorNote
            message={
              data.kill_switch
                ? "Kill switch active — the execution agent is rejecting every new order."
                : `Trading halted${data.halt_reason ? `: ${data.halt_reason}` : "."}`
            }
          />
        </div>
      )}

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Net asset value"
          value={money(data.nav)}
          hint={`${pct(data.total_return_pct)} since inception`}
          icon={<Wallet className="h-3 w-3" />}
        />
        <Stat
          label="Day P&L"
          value={money(data.day_pnl)}
          hint={pct(data.day_pnl_pct)}
          valueClass={tone(data.day_pnl)}
          icon={<TrendingUp className="h-3 w-3" />}
        />
        <Stat
          label="Cash"
          value={money(data.cash_usd)}
          hint={`${money(data.equity_value)} invested`}
          icon={<CircleDollarSign className="h-3 w-3" />}
        />
        <Stat
          label="Positions"
          value={data.positions_count}
          hint={`${money(data.unrealized_pnl)} unrealised`}
          icon={<Layers className="h-3 w-3" />}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Equity curve"
          subtitle="Portfolio snapshots, newest on the right"
          action={
            <Link to="/performance" className="btn btn-ghost text-xs">
              Performance <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
        >
          <EquityChart />
        </Card>

        <Card
          title="Live activity"
          subtitle="Straight off the agent bus"
          bodyClassName=""
        >
          <ActivityFeed />
        </Card>

        <Card
          title="Largest positions"
          action={
            <Link to="/portfolio" className="btn btn-ghost text-xs">
              All <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
          bodyClassName=""
        >
          {top.length === 0 ? (
            <Empty message="No open positions" hint="Signals become orders once the sleeves fire." />
          ) : (
            <ul className="divide-y divide-line/70">
              {top.map((p) => (
                <li key={p.symbol} className="flex items-center justify-between px-4 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink">{p.symbol}</div>
                    <div className="nums text-xs text-soft">
                      {p.quantity} @ {money(p.avg_entry_price, p.currency)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="nums text-sm text-ink">{money(p.market_value, p.currency)}</div>
                    <div className={`nums text-xs ${tone(p.unrealized_pnl)}`}>
                      {pct(p.return_pct)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Watchlist" subtitle="Latest marks" bodyClassName="">
          {!watchlist?.watchlist.length ? (
            <Empty message="No symbols priced yet" />
          ) : (
            <ul className="max-h-[280px] divide-y divide-line/70 overflow-y-auto">
              {watchlist.watchlist.map((w) => (
                <li key={w.symbol} className="flex items-center justify-between px-4 py-2">
                  <span className="text-sm text-ink">{w.symbol}</span>
                  <span className="flex items-center gap-3">
                    <span className="nums text-sm text-soft">
                      {w.price ? money(w.price) : "—"}
                    </span>
                    <span className={`nums w-16 text-right text-xs ${tone(w.change_pct)}`}>
                      {w.prev_close ? pct(w.change_pct) : "—"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Alerts" subtitle="Most recent first" bodyClassName="">
          {!alerts?.alerts.length ? (
            <Empty message="No alerts" hint="Risk, health and compliance alerts land here." />
          ) : (
            <ul className="max-h-[280px] divide-y divide-line/70 overflow-y-auto">
              {alerts.alerts.slice(0, 20).map((a) => (
                <li key={a.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm text-ink">{a.title}</span>
                    <Badge
                      tone={
                        a.severity?.toUpperCase() === "CRITICAL"
                          ? "bad"
                          : a.severity?.toUpperCase() === "WARNING"
                            ? "warn"
                            : "neutral"
                      }
                    >
                      {a.severity}
                    </Badge>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-soft">
                    <span className="truncate">{a.message}</span>
                  </div>
                  <div className="mt-0.5 text-2xs text-faint">{timeAgo(a.created_at)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token BBE68EA80F1F - verify with scripts/authorship.py verify
