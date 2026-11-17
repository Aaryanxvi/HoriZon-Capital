// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-588C25E30913
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useChartTheme } from "@/lib/colors";
import { withSign } from "./Tooltip";

export type DumbbellRow = { key: string; label: string; current: number; target: number };

export interface DumbbellProps {
  rows: DumbbellRow[];
  format: (v: number) => string;
  max?: number;
}

export function Dumbbell({ rows, format, max }: DumbbellProps) {
  const t = useChartTheme();
  if (!rows.length) return null;

  const all = rows.flatMap((r) => [r.current, r.target]);
  const lo = Math.min(0, ...all);
  const hi = max ?? Math.max(0, ...all);
  const pos = (v: number) => (hi > lo ? ((v - lo) / (hi - lo)) * 100 : 0);
  const dot = "absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full";
  const ring = `0 0 0 2px ${t.surface}`;

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-4 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: t.series[0] }} />
          current
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full border-2 border-ink" />
          target
        </span>
      </div>
      {rows.map((r) => {
        const a = pos(r.current);
        const b = pos(r.target);
        const gap = r.target - r.current;
        return (
          <div
            key={r.key}
            className="flex h-7 items-center gap-3 rounded px-1 transition-colors duration-100 hover:bg-surface-2"
            title={`${r.label}: current ${format(r.current)} · target ${format(r.target)} · gap ${withSign(gap, format)}`}
          >
            <span className="w-28 shrink-0 truncate text-sm text-ink">{r.label}</span>
            {/* inset by the dot radius so end dots are never clipped */}
            <span className="relative mx-[7px] h-7 flex-1">
              <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
              <span
                className="absolute top-1/2 h-0.5 -translate-y-1/2"
                style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%`, background: t.text3 }}
              />
              <span className={dot} style={{ left: `${a}%`, background: t.series[0], boxShadow: ring }} />
              <span className={`${dot} border-2 border-ink`} style={{ left: `${b}%`, boxShadow: ring }} />
            </span>
            <span className="nums w-20 shrink-0 text-right text-sm text-ink-2">{withSign(gap, format)}</span>
          </div>
        );
      })}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 588C25E30913 - verify with scripts/authorship.py verify
