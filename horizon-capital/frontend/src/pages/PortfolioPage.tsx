// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-C419CE29E10B
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useOverview, usePositions } from "@/lib/api";
import { tooltipStyle, useChartColors } from "@/lib/colors";
import { money, num, pct, timeAgo, tone } from "@/lib/format";
import { Card, Empty, Loading, PageHeader, Stat, Table } from "@/components/ui";

export default function PortfolioPage() {
  const { data, isLoading } = usePositions();
  const { data: overview } = useOverview();
  const colors = useChartColors();
  const SLICE_COLOURS = colors.series;

  if (isLoading) return <Loading label="Loading positions" />;

  const positions = data?.positions ?? [];
  const invested = positions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const unrealised = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0);
  const realised = positions.reduce((sum, p) => sum + p.realized_pnl, 0);

  const allocation = [
    ...positions.map((p) => ({ name: p.symbol, value: Math.abs(p.market_value) })),
    ...(overview && overview.cash_usd > 0
      ? [{ name: "Cash", value: overview.cash_usd }]
      : []),
  ].sort((a, b) => b.value - a.value);

  return (
    <>
      <PageHeader
        title="Portfolio"
        subtitle={`${positions.length} open position${positions.length === 1 ? "" : "s"}`}
      />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Invested" value={money(invested)} />
        <Stat label="Cash" value={money(overview?.cash_usd ?? 0)} />
        <Stat
          label="Unrealised P&L"
          value={money(unrealised)}
          valueClass={tone(unrealised)}
        />
        <Stat label="Realised P&L" value={money(realised)} valueClass={tone(realised)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Positions" bodyClassName="">
          {positions.length === 0 ? (
            <Empty
              message="No open positions"
              hint="The strategy sleeves only trade on >50bps drift from target weights."
            />
          ) : (
            <Table
              head={["Symbol", "Qty", "Entry", "Last", "Value", "Unrealised", "Return", "Updated"]}
            >
              {positions.map((p) => (
                <tr key={`${p.symbol}-${p.exchange}`} className="row-hover">
                  <td className="td">
                    <div className="font-medium">{p.symbol}</div>
                    <div className="text-2xs uppercase text-faint">
                      {p.exchange} · {p.side}
                    </div>
                  </td>
                  <td className="td nums text-right">{num(p.quantity, 4)}</td>
                  <td className="td nums text-right">{money(p.avg_entry_price, p.currency)}</td>
                  <td className="td nums text-right">{money(p.current_price, p.currency)}</td>
                  <td className="td nums text-right">{money(p.market_value, p.currency)}</td>
                  <td className={`td nums text-right ${tone(p.unrealized_pnl)}`}>
                    {money(p.unrealized_pnl, p.currency)}
                  </td>
                  <td className={`td nums text-right ${tone(p.return_pct)}`}>
                    {pct(p.return_pct)}
                  </td>
                  <td className="td text-right text-xs text-soft">{timeAgo(p.updated_at)}</td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Allocation" subtitle="Market value including cash">
          {allocation.length === 0 ? (
            <Empty message="Nothing allocated yet" />
          ) : (
            <>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={allocation}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={54}
                      outerRadius={86}
                      paddingAngle={2}
                      isAnimationActive={false}
                      stroke="none"
                    >
                      {allocation.map((_, i) => (
                        <Cell key={i} fill={SLICE_COLOURS[i % SLICE_COLOURS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={tooltipStyle(colors)}
                      formatter={(value: number) => money(value)}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="mt-2 space-y-1.5">
                {allocation.slice(0, 8).map((slice, i) => (
                  <li key={slice.name} className="flex items-center gap-2 text-sm">
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: SLICE_COLOURS[i % SLICE_COLOURS.length] }}
                    />
                    <span className="flex-1 truncate text-soft">{slice.name}</span>
                    <span className="nums text-xs text-soft">
                      {invested + (overview?.cash_usd ?? 0) > 0
                        ? `${((slice.value / (invested + (overview?.cash_usd ?? 0))) * 100).toFixed(1)}%`
                        : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token C419CE29E10B - verify with scripts/authorship.py verify
