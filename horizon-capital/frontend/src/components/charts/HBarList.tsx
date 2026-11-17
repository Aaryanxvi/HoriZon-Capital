// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-324D23FDFECD
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useChartTheme } from "@/lib/colors";

export type HBarRow = {
  key: string;
  label: string;
  sublabel?: string;
  value: number;
  marker?: number;
  markerLabel?: string;
};

export interface HBarListProps {
  rows: HBarRow[];
  format: (v: number) => string;
  max?: number;
  /** Default series slot 1 — nominal bars share one colour, never coloured by value. */
  color?: string;
  /** Rows past this fold into "Other" (default 12). */
  maxRows?: number;
  onRowClick?: (key: string) => void;
}

export const OTHER_KEY = "__other__";

export function HBarList({ rows, format, max, color, maxRows = 12, onRowClick }: HBarListProps) {
  const t = useChartTheme();
  if (!rows.length) return null;

  const shown =
    rows.length > maxRows
      ? [
          ...rows.slice(0, maxRows - 1),
          {
            key: OTHER_KEY,
            label: "Other",
            sublabel: `${rows.length - maxRows + 1} more`,
            value: rows.slice(maxRows - 1).reduce((sum, r) => sum + r.value, 0),
          } as HBarRow,
        ]
      : rows;
  const top = max ?? Math.max(...shown.map((r) => Math.max(r.value, r.marker ?? 0)), 0);
  const pos = (v: number) => `${top > 0 ? Math.min(Math.max(v / top, 0), 1) * 100 : 0}%`;
  const fill = color ?? t.series[0];

  return (
    <div className="flex flex-col">
      {shown.map((r) => {
        const tip =
          `${r.label}${r.sublabel ? ` (${r.sublabel})` : ""} · ${format(r.value)}` +
          (r.marker !== undefined ? ` · ${r.markerLabel ?? "marker"} ${format(r.marker)}` : "");
        const clickable = onRowClick && r.key !== OTHER_KEY;
        const Row = clickable ? "button" : "div";
        return (
          <Row
            key={r.key}
            {...(clickable ? { type: "button" as const, onClick: () => onRowClick(r.key) } : {})}
            title={tip}
            className="flex min-h-7 w-full items-center gap-3 rounded px-1 text-left transition-colors duration-100 hover:bg-surface-2"
          >
            <span className="w-28 shrink-0 py-0.5 leading-tight">
              <span className="block truncate text-sm text-ink">{r.label}</span>
              {r.sublabel && <span className="block truncate text-2xs text-ink-3">{r.sublabel}</span>}
            </span>
            <span className="relative h-7 flex-1">
              <span
                className="absolute left-0 top-1/2 h-3.5 -translate-y-1/2 rounded-r-[3px]"
                style={{ width: pos(r.value), background: fill }}
              />
              {r.marker !== undefined && (
                <span
                  className="absolute bottom-0 top-0 w-px bg-ink-3"
                  style={{ left: pos(r.marker) }}
                  title={`${r.markerLabel ?? "marker"} ${format(r.marker)}`}
                />
              )}
            </span>
            <span className="nums w-20 shrink-0 text-right text-sm text-ink-2">{format(r.value)}</span>
          </Row>
        );
      })}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 324D23FDFECD - verify with scripts/authorship.py verify
