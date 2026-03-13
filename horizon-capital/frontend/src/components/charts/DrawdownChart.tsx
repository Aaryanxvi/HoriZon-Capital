import { useMemo } from "react";
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

function generateDrawdownData() {
  const data: { date: string; drawdown: number }[] = [];
  let peak = 1_000_000;
  let current = peak;

  for (let i = 0; i < 90; i++) {
    current += (Math.random() - 0.45) * 20000;
    if (current > peak) peak = current;
    const dd = ((current - peak) / peak) * 100;
    const d = new Date(Date.now() - (90 - i) * 86400000);
    data.push({
      date: `${d.getDate()}/${d.getMonth() + 1}`,
      drawdown: Math.round(dd * 100) / 100,
    });
  }
  return data;
}

interface DrawdownChartProps {
  height?: number;
}

export default function DrawdownChart({ height = 250 }: DrawdownChartProps) {
  const data = useMemo(generateDrawdownData, []);
  const maxDD = Math.min(...data.map((d) => d.drawdown));

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-white">Drawdown from Peak</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Max: <span className="text-accent-red font-bold">{maxDD.toFixed(2)}%</span>
          </p>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
          <defs>
            <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0.4} />
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
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
            reversed
            domain={["dataMin", 0]}
          />
          <ReferenceLine y={0} stroke="#374151" />
          <ReferenceLine
            y={maxDD}
            stroke="#ef4444"
            strokeDasharray="4 4"
            label={{
              value: `Max DD: ${maxDD.toFixed(2)}%`,
              position: "insideBottomLeft",
              fill: "#ef4444",
              fontSize: 10,
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #1f2937",
              borderRadius: 8,
              fontSize: 11,
            }}
            formatter={(val: number) => [`${val.toFixed(2)}%`, "Drawdown"]}
            labelStyle={{ color: "#9ca3af" }}
          />
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="#ef4444"
            strokeWidth={2}
            fill="url(#ddGrad)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
