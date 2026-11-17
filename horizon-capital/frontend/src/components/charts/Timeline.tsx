// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-97B6C52C9454
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useState } from "react";
import { useChartTheme } from "@/lib/colors";
import { dateTime } from "@/lib/format";
import { Tooltip, useWidth } from "./Tooltip";

export type TimelineEvent = {
  time: number; // unix seconds
  symbol: string;
  side: "BUY" | "SELL";
  kind: "order" | "fill";
  size: number;
  label: string;
};

export interface TimelineProps {
  events: TimelineEvent[];
  maxRows?: number;
}

const ROW = 28;
const LABEL_W = 96;
const AXIS = 20;
const PAD_X = 12; // keeps the largest mark (r 7 + ring) inside the plot
const DAY = 86_400;

export function Timeline({ events, maxRows = 10 }: TimelineProps) {
  const t = useChartTheme();
  const [box, width] = useWidth<HTMLDivElement>();
  const [focus, setFocus] = useState<number | null>(null);
  if (!events.length) return null;

  // Lanes: symbols by event count, tail folded into "Other".
  const counts = new Map<string, number>();
  for (const e of events) counts.set(e.symbol, (counts.get(e.symbol) ?? 0) + 1);
  const ranked = [...counts].sort((a, b) => b[1] - a[1]).map(([s]) => s);
  const lanes = ranked.length > maxRows ? [...ranked.slice(0, maxRows - 1), "Other"] : ranked;
  const lane = (symbol: string) => {
    const i = lanes.indexOf(symbol);
    return i === -1 ? lanes.length - 1 : i;
  };

  // Mark radius by size tercile.
  const sizes = events.map((e) => e.size).sort((a, b) => a - b);
  const t1 = sizes[Math.floor(sizes.length / 3)];
  const t2 = sizes[Math.floor((2 * sizes.length) / 3)];
  const radius = (s: number) => (s <= t1 ? 4 : s <= t2 ? 5.5 : 7);

  let lo = Math.min(...events.map((e) => e.time));
  let hi = Math.max(...events.map((e) => e.time));
  if (hi - lo < 3600) {
    lo -= DAY / 2;
    hi += DAY / 2;
  }
  const plotL = LABEL_W + PAD_X;
  const plotW = Math.max(0, width - plotL - PAD_X);
  const x = (s: number) => plotL + ((s - lo) / (hi - lo)) * plotW;
  const height = lanes.length * ROW + AXIS;

  // Local-midnight day ticks, thinned to keep labels ≥ ~56px apart.
  const first = new Date(lo * 1000);
  first.setHours(24, 0, 0, 0);
  const days: number[] = [];
  for (const d = first; d.getTime() / 1000 <= hi; d.setDate(d.getDate() + 1)) days.push(d.getTime() / 1000);
  const step = Math.max(1, Math.ceil(days.length / Math.max(1, Math.floor(plotW / 56))));

  const order = events.map((_, i) => i).sort((a, b) => events[a].time - events[b].time);
  const active = focus === null ? null : events[focus];

  return (
    <div>
      <div ref={box} className="relative w-full" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height}>
            {lanes.map((s, i) => (
              <g key={s}>
                <line x1={0} x2={width} y1={(i + 1) * ROW} y2={(i + 1) * ROW} stroke={t.grid} strokeWidth={1} />
                <text x={0} y={i * ROW + ROW / 2} dy="0.32em" fontSize={12} fill={t.text}>
                  {s.length > 12 ? `${s.slice(0, 11)}…` : s}
                </text>
              </g>
            ))}
            {days.map((d, i) => (
              <g key={d}>
                <line x1={x(d)} x2={x(d)} y1={0} y2={lanes.length * ROW} stroke={t.grid} strokeWidth={1} />
                {i % step === 0 && (
                  <text x={x(d)} y={height - 6} textAnchor="middle" fontSize={11} fill={t.text3}>
                    {new Date(d * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </text>
                )}
              </g>
            ))}
            {order.map((i) => {
              const e = events[i];
              const cx = x(e.time);
              const cy = lane(e.symbol) * ROW + ROW / 2;
              const r = radius(e.size);
              const color = e.side === "BUY" ? t.up : t.down;
              return (
                <g
                  key={i}
                  tabIndex={0}
                  role="img"
                  aria-label={`${dateTime(new Date(e.time * 1000).toISOString())} · ${e.label}`}
                  className="cursor-default outline-none"
                  onPointerEnter={() => setFocus(i)}
                  onPointerLeave={() => setFocus(null)}
                  onFocus={() => setFocus(i)}
                  onBlur={() => setFocus(null)}
                >
                  <circle cx={cx} cy={cy} r={12} fill="transparent" />
                  <circle cx={cx} cy={cy} r={r + 2} fill={t.surface} />
                  {e.kind === "fill" ? (
                    <circle cx={cx} cy={cy} r={r} fill={color} />
                  ) : (
                    <circle cx={cx} cy={cy} r={r - 1} fill={t.surface} stroke={color} strokeWidth={2} />
                  )}
                  {focus === i && <circle cx={cx} cy={cy} r={r + 3} fill="none" stroke={t.accent} strokeWidth={2} />}
                </g>
              );
            })}
          </svg>
        )}
        {active && (
          <Tooltip
            x={x(active.time)}
            y={lane(active.symbol) * ROW + ROW / 2}
            width={width}
            title={dateTime(new Date(active.time * 1000).toISOString())}
            rows={[{ value: active.label, color: active.side === "BUY" ? t.up : t.down }]}
          />
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-ink-3" />
          fill
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full border-2 border-ink-3" />
          order
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: t.up }} />▲ buy
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: t.down }} />▼ sell
        </span>
      </div>
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 97B6C52C9454 - verify with scripts/authorship.py verify
