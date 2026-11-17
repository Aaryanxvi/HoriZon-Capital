// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-94498691F800
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState } from "react";
import { useChartTheme } from "@/lib/colors";
import { histogramBins } from "@/lib/series";
import { Tooltip, useWidth } from "./Tooltip";

export interface HistogramProps {
  values: number[];
  bins?: number;
  format: (v: number) => string;
  refs?: { value: number; label: string }[];
}

const HEIGHT = 180;
const M = { top: 18, right: 8, bottom: 20, left: 32 };
const MAX_BAR = 24;

// Column with rounded top corners (r ≤ 3) and a square base.
function column(x: number, y: number, w: number, h: number): string {
  const r = Math.min(3, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export function Histogram({ values, bins = 15, format, refs }: HistogramProps) {
  const t = useChartTheme();
  const [box, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const data = histogramBins(values, bins);
  const total = data.reduce((s, b) => s + b.count, 0);

  const plotW = Math.max(0, width - M.left - M.right);
  const plotH = HEIGHT - M.top - M.bottom;
  const lo = data[0]?.x0 ?? 0;
  const hi = data[data.length - 1]?.x1 ?? 1;
  const x = (v: number) => M.left + ((v - lo) / (hi - lo || 1)) * plotW;
  const peak = Math.max(1, ...data.map((b) => b.count));
  const yMax = Math.ceil(peak / 3) * 3; // three integer gridlines
  const y = (c: number) => M.top + plotH - (c / yMax) * plotH;
  const slot = data.length ? plotW / data.length : 0;
  const barW = Math.max(1, Math.min(MAX_BAR, slot - 2)); // 2px surface gap between neighbours
  const edgeStep = Math.max(2, Math.ceil(48 / Math.max(slot, 1)));

  const summary = total
    ? `Distribution of ${total} values from ${format(Math.min(...values.filter(Number.isFinite)))} to ${format(Math.max(...values.filter(Number.isFinite)))}`
    : "No values";
  const hovered = hover === null ? null : data[hover];

  return (
    <div ref={box} className="relative w-full" style={{ height: HEIGHT }}>
      {width > 0 && data.length > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={summary} onPointerLeave={() => setHover(null)}>
          {[1, 2, 3].map((k) => (
            <g key={k}>
              <line x1={M.left} x2={width - M.right} y1={y((yMax / 3) * k)} y2={y((yMax / 3) * k)} stroke={t.grid} strokeWidth={1} />
              <text x={M.left - 6} y={y((yMax / 3) * k)} dy="0.32em" textAnchor="end" fontSize={11} fill={t.text3} className="nums">
                {(yMax / 3) * k}
              </text>
            </g>
          ))}
          {data.map((b, i) => {
            const h = y(0) - y(b.count);
            const bx = x(b.x0) + (slot - barW) / 2;
            return b.count > 0 ? (
              <path key={i} d={column(bx, y(b.count), barW, h)} fill={t.series[0]} opacity={hover === null || hover === i ? 1 : 0.55} />
            ) : null;
          })}
          {lo < 0 && hi > 0 && <line x1={x(0)} x2={x(0)} y1={M.top} y2={y(0)} stroke={t.border} strokeWidth={1} />}
          <line x1={M.left} x2={width - M.right} y1={y(0)} y2={y(0)} stroke={t.border} strokeWidth={1} />
          {[...data.map((b) => b.x0), hi].map((edge, i) =>
            i % edgeStep === 0 ? (
              <text key={i} x={x(edge)} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill={t.text3} className="nums">
                {format(edge)}
              </text>
            ) : null,
          )}
          {refs?.map((r, i) => (
            <g key={i}>
              <line x1={x(r.value)} x2={x(r.value)} y1={M.top - 2} y2={M.top + 8} stroke={t.accentStrong} strokeWidth={2} />
              <text x={x(r.value)} y={M.top - 6} textAnchor="middle" fontSize={11} fill={t.text2}>
                {r.label}
              </text>
            </g>
          ))}
          {data.map((b, i) => (
            <rect
              key={i}
              x={x(b.x0)}
              y={M.top}
              width={slot}
              height={plotH}
              fill="transparent"
              onPointerEnter={() => setHover(i)}
            />
          ))}
        </svg>
      )}
      {hovered && hover !== null && (
        <Tooltip
          x={x(hovered.x0) + slot / 2}
          y={y(hovered.count) - 8}
          width={width}
          title={`${format(hovered.x0)} to ${format(hovered.x1)}`}
          rows={[{ value: `${hovered.count} (${total ? Math.round((hovered.count / total) * 100) : 0}%)`, label: "count", color: t.series[0] }]}
        />
      )}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 94498691F800 - verify with scripts/authorship.py verify
