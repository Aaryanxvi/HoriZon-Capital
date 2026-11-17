// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-D93822D73A90
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useMemo } from "react";

import { Bullet, ChartCard, HBarList, StatTile, TimeSeries, type TSSeries } from "@/components/charts";
import { Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useOverview, usePositions, useRisk } from "@/lib/api";
import { useChartTheme } from "@/lib/colors";
import { dateTime, money, num } from "@/lib/format";
import { allocationRows, CASH_KEY, exposure } from "@/lib/portfolio";

const pctFmt = (v: number) => `${num(v, 2)}%`;
const timesFmt = (v: number) => `${num(v, 2)}×`;
const weightFmt = (v: number) => `${num(v, 1)}%`;
// The risk agent stores VaR/CVaR as a FRACTION of NAV (0.001 = 0.10%), not dollars.
const varPctFmt = (v: number) => `${num(v, 2)}%`;
// Drawdown is plotted ≤ 0 (percent); show it with a real minus sign.
const ddFmt = (v: number) => (v === 0 ? "0.00%" : `−${num(Math.abs(v), 2)}%`);

// Risk snapshot timestamps look like "2026-08-30 17:11:38.363417+00:00"; bare ones are UTC.
function unixSeconds(ts: string): number {
  const iso = ts.replace(" ", "T");
  return Math.floor(Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`) / 1000);
}

export default function RiskPage() {
  const theme = useChartTheme();
  const riskQ = useRisk();
  const overviewQ = useOverview();
  const positionsQ = usePositions();

  const risk = riskQ.data;
  const overview = overviewQ.data;
  const latest = risk?.latest ?? null;
  const limits: Record<string, number | null> = risk?.limits ?? {};
  const positions = positionsQ.data?.positions ?? [];
  const nav = overview?.nav ?? 0;
  const exp = exposure(positions, nav);
  const concentration = allocationRows(positions, nav, 0, limits.max_position_pct).filter((r) => r.key !== CASH_KEY);

  const history = risk?.history;
  const { varData, ddData, varRows, ddRows } = useMemo(() => {
    const points = (history ?? [])
      .map((h) => ({ time: unixSeconds(h.created_at), h }))
      .filter((p) => Number.isFinite(p.time));
    const newestFirst = [...points].sort((a, b) => b.time - a.time);
    return {
      varData: points.map((p) => ({ time: p.time, value: p.h.var_1d_95 * 100 })),
      ddData: points.map((p) => ({ time: p.time, value: -Math.abs(p.h.current_drawdown) * 100 })),
      varRows: newestFirst.map((p) => [dateTime(p.h.created_at), varPctFmt(p.h.var_1d_95 * 100)]),
      ddRows: newestFirst.map((p) => [dateTime(p.h.created_at), ddFmt(-Math.abs(p.h.current_drawdown) * 100)]),
    };
  }, [history]);

  const varSeries = useMemo<TSSeries[]>(
    () => [{ id: "var95", label: "VaR 1d 95%", kind: "line", data: varData, color: theme.series[0], format: varPctFmt }],
    [varData, theme],
  );
  // Baseline at 0 in the down colour: the fill sits between zero and the curve (underwater
  // chart). A plain area series fills to the pane bottom, which would shade "no drawdown".
  const ddSeries = useMemo<TSSeries[]>(
    () => [
      {
        id: "dd",
        label: "Drawdown",
        kind: "baseline",
        data: ddData,
        baseValue: 0,
        upColor: theme.down,
        downColor: theme.down,
        format: ddFmt,
      },
    ],
    [ddData, theme],
  );

  const n = varData.length;
  const historyEmpty =
    n >= 2
      ? null
      : {
          message: n === 0 ? "No risk snapshots yet" : "Not enough risk history yet",
          hint: "The risk agent writes a snapshot every 30 s while the engine runs; the chart needs two.",
        };
  const historySubtitle = n ? `last ${n} risk snapshots (~30 s apart)` : undefined;

  const loading = riskQ.isLoading || overviewQ.isLoading || positionsQ.isLoading;
  const error = riskQ.error ?? overviewQ.error ?? positionsQ.error;
  const varPct = latest ? latest.var_1d_95 * 100 : 0;
  const positionLimit = limits.max_position_pct ?? null;

  return (
    <>
      <PageHeader title="Risk" subtitle="Pre-trade limits, live VaR and the drawdown kill switch" />

      <div className="space-y-3">
        {(risk?.halted || overview?.kill_switch) && (
          <ErrorNote
            message={
              overview?.kill_switch
                ? "Kill switch active — new orders are being rejected at the execution gate."
                : `Trading halted${risk?.halt_reason ? `: ${risk.halt_reason}` : "."}`
            }
          />
        )}

        {loading ? (
          <Card>
            <Loading label="Loading risk metrics" />
          </Card>
        ) : error ? (
          <ErrorNote message={error.message} />
        ) : !latest || !overview ? (
          <Card>
            <Empty
              message="No risk snapshot yet"
              hint="The risk agent writes VaR, CVaR and drawdown every 30 seconds while the engine runs."
            />
          </Card>
        ) : (
          <>
            <Card
              title="Limits"
              subtitle="Breaching one halts new risk"
              bodyClassName="grid gap-x-6 gap-y-4 p-3 md:grid-cols-2 xl:grid-cols-5"
            >
              <Bullet
                label="Drawdown"
                value={Math.abs(latest.current_drawdown) * 100}
                limit={limits.max_drawdown_pct ?? null}
                format={pctFmt}
              />
              <Bullet
                label="Daily loss"
                value={Math.max(0, -overview.day_pnl_pct)}
                limit={limits.daily_loss_limit_pct ?? null}
                format={pctFmt}
                note={overview.day_pnl_pct > 0 ? `+${num(overview.day_pnl_pct, 2)}% today` : undefined}
              />
              <Bullet
                label="VaR 1d 95% of NAV"
                value={varPct}
                limit={limits.var_limit_pct ?? null}
                format={pctFmt}
              />
              <Bullet
                label="Largest position"
                value={exp.largest?.weightPct ?? 0}
                limit={positionLimit}
                format={pctFmt}
                note={exp.largest?.symbol ?? "no open positions"}
              />
              <Bullet
                label="Gross leverage"
                value={exp.gross}
                limit={limits.max_leverage ?? null}
                format={timesFmt}
              />
            </Card>

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="VaR 1d 95%"
                value={money(latest.var_1d_95 * nav)}
                hint={`${num(varPct, 2)}% of NAV`}
              />
              <StatTile
                label="VaR 1d 99%"
                value={money(latest.var_1d_99 * nav)}
                hint={`${num(latest.var_1d_99 * 100, 2)}% of NAV`}
              />
              <StatTile label="CVaR 1d 95%" value={money(latest.cvar_1d_95 * nav)} hint="avg loss beyond VaR 95" />
              <StatTile
                label="Max drawdown"
                value={ddFmt(-Math.abs(latest.max_drawdown) * 100)}
                hint={`current ${ddFmt(-Math.abs(latest.current_drawdown) * 100)}`}
              />
            </div>
          </>
        )}

        <div className="grid gap-3 lg:grid-cols-3">
          <div className="space-y-3 lg:col-span-2">
            <ChartCard
              title="VaR 1d 95% (% of NAV)"
              subtitle={historySubtitle}
              isLoading={riskQ.isLoading}
              isFetching={riskQ.isFetching}
              error={riskQ.error?.message ?? null}
              empty={historyEmpty}
              height={170}
              table={{ columns: ["Time", "VaR 1d 95%"], rows: varRows }}
            >
              <TimeSeries series={varSeries} height={170} syncKey="risk" timeVisible />
            </ChartCard>
            <ChartCard
              title="Drawdown"
              subtitle={historySubtitle}
              isLoading={riskQ.isLoading}
              isFetching={riskQ.isFetching}
              error={riskQ.error?.message ?? null}
              empty={historyEmpty}
              height={170}
              table={{ columns: ["Time", "Drawdown"], rows: ddRows }}
            >
              <TimeSeries series={ddSeries} height={170} syncKey="risk" timeVisible />
            </ChartCard>
          </div>

          <ChartCard
            title="Concentration"
            subtitle={
              positionLimit !== null ? `% of NAV · tick = ${weightFmt(positionLimit)} limit` : "% of NAV · no position limit set"
            }
            isLoading={positionsQ.isLoading || overviewQ.isLoading}
            isFetching={positionsQ.isFetching}
            error={positionsQ.error?.message ?? overviewQ.error?.message ?? null}
            empty={
              concentration.length
                ? null
                : positions.length
                  ? { message: "NAV not available yet", hint: "Weights need the portfolio agent's first NAV snapshot." }
                  : { message: "No open positions", hint: "Positions appear after the first fill." }
            }
            table={{
              columns: ["Symbol", "Value", "Weight"],
              rows: concentration.map((r) => [r.label, r.sublabel ?? "", weightFmt(r.value)]),
            }}
          >
            <HBarList rows={concentration} format={weightFmt} />
          </ChartCard>
        </div>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token D93822D73A90 - verify with scripts/authorship.py verify
