import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useEquityCurve, useOverview, usePerformance } from "@/lib/api";
import { tooltipStyle, useChartColors } from "@/lib/colors";
import { axisMoney, dateTime, money, num, pct, tone } from "@/lib/format";
import { Card, Empty, Loading, PageHeader, Stat, Table } from "@/components/ui";

const METRICS: { key: string; label: string; format: (v: number) => string }[] = [
  { key: "total_return", label: "Total return", format: (v) => pct(v * 100) },
  { key: "annualized_return", label: "Annualised", format: (v) => pct(v * 100) },
  { key: "sharpe_ratio", label: "Sharpe", format: (v) => num(v, 2) },
  { key: "sortino_ratio", label: "Sortino", format: (v) => num(v, 2) },
  { key: "calmar_ratio", label: "Calmar", format: (v) => num(v, 2) },
  { key: "max_drawdown", label: "Max drawdown", format: (v) => `${(Math.abs(v) * 100).toFixed(2)}%` },
  { key: "win_rate", label: "Win rate", format: (v) => `${(v * 100).toFixed(1)}%` },
  { key: "profit_factor", label: "Profit factor", format: (v) => num(v, 2) },
];

export default function PerformancePage() {
  const { data, isLoading } = usePerformance();
  const { data: curve } = useEquityCurve();
  const { data: overview } = useOverview();
  const colors = useChartColors();

  if (isLoading) return <Loading label="Loading performance" />;

  const periods = data?.periods ?? {};
  const points = (curve?.points ?? []).map((p) => ({ t: p.created_at, value: p.total_value }));
  const values = points.map((p) => p.value);
  const [minValue, maxValue] = [Math.min(...values), Math.max(...values)];

  return (
    <>
      <PageHeader
        title="Performance"
        subtitle="Written by the performance worker every 15 minutes, benchmarked against ^NSEI and ^GSPC"
      />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="NAV" value={money(overview?.nav)} />
        <Stat
          label="Since inception"
          value={pct(overview?.total_return_pct ?? 0)}
          valueClass={tone(overview?.total_return_pct ?? 0)}
          hint={`from ${money(overview?.initial_capital)}`}
        />
        <Stat
          label="Day P&L"
          value={money(overview?.day_pnl)}
          valueClass={tone(overview?.day_pnl ?? 0)}
          hint={pct(overview?.day_pnl_pct ?? 0)}
        />
        <Stat
          label="Trades"
          value={Number(data?.latest?.total_trades ?? 0)}
          hint={data?.latest ? `as of ${dateTime(String(data.latest.created_at))}` : undefined}
        />
      </div>

      <Card className="mb-4" title="Equity curve">
        {points.length < 2 ? (
          <Empty message="Not enough snapshots yet" />
        ) : (
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="perfFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={colors.clay} stopOpacity={0.2} />
                    <stop offset="100%" stopColor={colors.clay} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="t" hide />
                <YAxis
                  domain={["dataMin", "dataMax"]}
                  width={64}
                  tick={{ fontSize: 11, fill: colors.faint }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => axisMoney(v, minValue, maxValue)}
                />
                <Tooltip
                  contentStyle={tooltipStyle(colors)}
                  labelFormatter={(label: string) => dateTime(label)}
                  formatter={(value: number) => [money(value), "NAV"]}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={colors.clay}
                  strokeWidth={1.75}
                  fill="url(#perfFill)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="Metrics by period" bodyClassName="">
        {Object.keys(periods).length === 0 ? (
          <Empty
            message="No performance snapshots yet"
            hint="The first window lands about 15 minutes after start."
          />
        ) : (
          <Table head={["Period", ...METRICS.map((m) => m.label), "Alpha IN", "Alpha US"]}>
            {Object.entries(periods).map(([period, row]) => (
              <tr key={period} className="row-hover">
                <td className="td font-medium uppercase">{period}</td>
                {METRICS.map((metric) => (
                  <td key={metric.key} className="td nums text-right">
                    {metric.format(Number(row[metric.key] ?? 0))}
                  </td>
                ))}
                <td className="td nums text-right">{num(Number(row.alpha_india ?? 0), 3)}</td>
                <td className="td nums text-right">{num(Number(row.alpha_us ?? 0), 3)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
