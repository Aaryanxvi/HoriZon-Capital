// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-D93822D73A90
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useOverview, useRisk } from "@/lib/api";
import { tooltipStyle, useChartColors } from "@/lib/colors";
import { clock, money, num } from "@/lib/format";
import { Card, Empty, ErrorNote, Loading, PageHeader, Stat } from "@/components/ui";

function LimitBar({
  label,
  used,
  limit,
  unit = "%",
}: {
  label: string;
  used: number;
  limit: number | null | undefined;
  unit?: string;
}) {
  const ratio = limit ? Math.min(Math.abs(used) / limit, 1) : 0;
  const colour = ratio > 0.85 ? "bg-down" : ratio > 0.6 ? "bg-warn" : "bg-up";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-soft">{label}</span>
        <span className="nums text-soft">
          {num(Math.abs(used), 2)}
          {unit} / {limit !== null && limit !== undefined ? `${num(limit, 2)}${unit}` : "—"}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-line">
        <div className={`h-full rounded-full ${colour}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export default function RiskPage() {
  const { data, isLoading } = useRisk();
  const { data: overview } = useOverview();
  const colors = useChartColors();

  if (isLoading) return <Loading label="Loading risk metrics" />;

  const latest = data?.latest;
  const nav = overview?.nav ?? 0;
  const history = (data?.history ?? []).map((point) => ({
    t: point.created_at,
    var95: point.var_1d_95,
    drawdown: Math.abs(point.current_drawdown) * 100,
  }));

  return (
    <>
      <PageHeader
        title="Risk"
        subtitle="Pre-trade limits, live VaR and the drawdown kill switch"
      />

      {(data?.halted || overview?.kill_switch) && (
        <div className="mb-5">
          <ErrorNote
            message={
              overview?.kill_switch
                ? "Kill switch active — new orders are being rejected at the execution gate."
                : `Trading halted${data?.halt_reason ? `: ${data.halt_reason}` : "."}`
            }
          />
        </div>
      )}

      {!latest ? (
        <Card>
          <Empty
            message="No risk snapshot yet"
            hint="The risk agent writes VaR, CVaR and drawdown every 30 seconds."
          />
        </Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat
              label="VaR 1d 95%"
              value={money(latest.var_1d_95)}
              hint={nav ? `${((latest.var_1d_95 / nav) * 100).toFixed(2)}% of NAV` : undefined}
            />
            <Stat label="VaR 1d 99%" value={money(latest.var_1d_99)} />
            <Stat label="CVaR 95%" value={money(latest.cvar_1d_95)} />
            <Stat
              label="Drawdown"
              value={`${(Math.abs(latest.current_drawdown) * 100).toFixed(2)}%`}
              hint={`max ${(Math.abs(latest.max_drawdown) * 100).toFixed(2)}%`}
              valueClass={
                Math.abs(latest.current_drawdown) * 100 >
                (data?.limits.max_drawdown_pct ?? 100) * 0.8
                  ? "text-down"
                  : undefined
              }
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2" title="VaR and drawdown history">
              {history.length < 2 ? (
                <Empty message="Not enough history yet" />
              ) : (
                <div className="h-[240px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <XAxis dataKey="t" hide />
                      <YAxis
                        yAxisId="left"
                        width={62}
                        tick={{ fontSize: 11, fill: colors.faint }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        width={44}
                        unit="%"
                        tick={{ fontSize: 11, fill: colors.faint }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip
                        contentStyle={tooltipStyle(colors)}
                        labelFormatter={(label: string) => clock(label)}
                      />
                      <Line
                        yAxisId="left"
                        type="monotone"
                        dataKey="var95"
                        name="VaR 95%"
                        stroke={colors.clay}
                        strokeWidth={1.75}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="drawdown"
                        name="Drawdown %"
                        stroke={colors.down}
                        strokeWidth={1.5}
                        strokeDasharray="4 3"
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            <Card title="Limits" subtitle="Breaching one halts new risk">
              <div className="space-y-4">
                <LimitBar
                  label="Drawdown"
                  used={Math.abs(latest.current_drawdown) * 100}
                  limit={data?.limits.max_drawdown_pct}
                />
                <LimitBar
                  label="VaR of NAV"
                  used={nav ? (latest.var_1d_95 / nav) * 100 : 0}
                  limit={data?.limits.var_limit_pct}
                />
                <div className="space-y-2 border-t border-line pt-3 text-xs text-soft">
                  <div className="flex justify-between">
                    <span>Max position</span>
                    <span className="nums">{num(data?.limits.max_position_pct ?? 0, 1)}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Max leverage</span>
                    <span className="nums">{num(data?.limits.max_leverage ?? 0, 1)}x</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Daily loss limit</span>
                    <span className="nums">
                      {num(data?.limits.daily_loss_limit_pct ?? 0, 1)}%
                    </span>
                  </div>
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token D93822D73A90 - verify with scripts/authorship.py verify
