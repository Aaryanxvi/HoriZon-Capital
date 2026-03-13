import { useState, useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import clsx from "clsx";

const PERIODS = ["1D", "7D", "30D", "90D", "YTD", "ALL"] as const;
type Period = (typeof PERIODS)[number];

// Generate mock data
function generateMockData(period: Period) {
  const now = Date.now();
  const points: { date: string; pnl: number; timestamp: number }[] = [];
  let intervals: number;
  let step: number;

  switch (period) {
    case "1D":
      intervals = 78;
      step = 5 * 60 * 1000;
      break;
    case "7D":
      intervals = 7 * 24;
      step = 60 * 60 * 1000;
      break;
    case "30D":
      intervals = 30;
      step = 24 * 60 * 60 * 1000;
      break;
    case "90D":
      intervals = 90;
      step = 24 * 60 * 60 * 1000;
      break;
    case "YTD":
      intervals = 72;
      step = 24 * 60 * 60 * 1000;
      break;
    default:
      intervals = 365;
      step = 24 * 60 * 60 * 1000;
  }

  let cumPnl = 0;
  for (let i = 0; i < intervals; i++) {
    cumPnl += (Math.random() - 0.45) * 50000;
    const ts = now - (intervals - i) * step;
    const d = new Date(ts);
    const label =
      period === "1D"
        ? `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`
        : `${d.getDate()}/${d.getMonth() + 1}`;
    points.push({ date: label, pnl: Math.round(cumPnl), timestamp: ts });
  }
  return points;
}

function formatCurrency(val: number) {
  const abs = Math.abs(val);
  if (abs >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(val / 1_000).toFixed(1)}K`;
  return val.toFixed(0);
}

interface PnLChartProps {
  height?: number;
}

export default function PnLChart({ height = 300 }: PnLChartProps) {
  const [period, setPeriod] = useState<Period>("30D");
  const data = useMemo(() => generateMockData(period), [period]);

  const latest = data[data.length - 1]?.pnl ?? 0;
  const isPositive = latest >= 0;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">P&L Curve</h3>
          <p
            className={clsx(
              "text-lg font-bold mt-0.5",
              isPositive ? "text-accent-green" : "text-accent-red"
            )}
          >
            {isPositive ? "+" : ""}
            {formatCurrency(latest)}
          </p>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={clsx(
                "px-2.5 py-1 text-[10px] font-bold rounded transition-colors",
                p === period
                  ? "bg-accent-blue/20 text-accent-blue border border-accent-blue/20"
                  : "text-gray-500 hover:text-gray-300 border border-transparent"
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
          <defs>
            <linearGradient id="pnlGreenGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="pnlRedGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.3} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "#6b7280" }}
            axisLine={{ stroke: "#1f2937" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: "#6b7280" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => formatCurrency(v)}
          />
          <ReferenceLine y={0} stroke="#374151" strokeDasharray="3 3" />
          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #1f2937",
              borderRadius: 8,
              fontSize: 11,
            }}
            formatter={(val: number) => [
              `${val >= 0 ? "+" : ""}${formatCurrency(val)}`,
              "P&L",
            ]}
            labelStyle={{ color: "#9ca3af" }}
          />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? "#10b981" : "#ef4444"}
            strokeWidth={2}
            fill={isPositive ? "url(#pnlGreenGrad)" : "url(#pnlRedGrad)"}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
