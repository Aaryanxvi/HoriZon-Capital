// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-EB88D79B2AA7
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useChartTheme } from "@/lib/colors";

export interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  /** "neutral" strokes in the muted ink; "direction" strokes up/down by first → last. */
  tone?: "neutral" | "direction";
  /** Reference level: drawn as a hairline and used instead of the first point for direction. */
  baseline?: number;
  title?: string;
}

const PAD = 5; // end dot r 2.5 + 2px surface ring

export function Sparkline({ data, width = 96, height = 28, tone = "neutral", baseline, title }: SparklineProps) {
  const t = useChartTheme();
  const values = data.filter(Number.isFinite);
  if (values.length < 2) return null;

  const ref = baseline ?? values[0];
  const last = values[values.length - 1];
  const dirColor = last > ref ? t.up : last < ref ? t.down : t.text3;
  const stroke = tone === "direction" ? dirColor : t.text3;

  const lo = Math.min(...values, baseline ?? Infinity);
  const hi = Math.max(...values, baseline ?? -Infinity);
  const span = hi - lo || 1;
  const x = (i: number) => PAD + (i / (values.length - 1)) * (width - 2 * PAD);
  const y = (v: number) => PAD + (1 - (v - lo) / span) * (height - 2 * PAD);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const bottom = height - PAD;
  const area = `${line}L${x(values.length - 1).toFixed(1)},${bottom}L${x(0).toFixed(1)},${bottom}Z`;
  const label = title ?? "Trend";

  return (
    <svg width={width} height={height} role="img" aria-label={label} className="block">
      <title>{label}</title>
      {baseline !== undefined && (
        <line x1={PAD} x2={width - PAD} y1={y(baseline)} y2={y(baseline)} stroke={t.grid} strokeWidth={1} />
      )}
      <path d={area} fill={stroke} fillOpacity={0.1} />
      <path d={line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} fill={dirColor} stroke={t.surface} strokeWidth={4} paintOrder="stroke" />
    </svg>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token EB88D79B2AA7 - verify with scripts/authorship.py verify
