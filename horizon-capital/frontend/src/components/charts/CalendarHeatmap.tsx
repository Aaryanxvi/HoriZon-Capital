// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-1DF0D05D0AB4
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { useChartTheme, withAlpha, type ChartTheme } from "@/lib/colors";
import { withSign } from "./Tooltip";

export type CalendarCell = { year: number; month: number; value: number | null; partial?: boolean };

export interface CalendarHeatmapProps {
  cells: CalendarCell[];
  format: (v: number) => string;
  yearTotals?: Record<number, number | null>;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Diverging: down ↔ up poles over a neutral midpoint; magnitude = pole alpha 0.14 → 0.72.
function tint(v: number, vmax: number, t: ChartTheme): string {
  if (v === 0 || vmax === 0) return t.divergingMid;
  return withAlpha(v > 0 ? t.up : t.down, 0.14 + 0.58 * Math.min(Math.abs(v) / vmax, 1));
}

function years(cells: CalendarCell[]): number[] {
  return [...new Set(cells.map((c) => c.year))].sort((a, b) => b - a);
}

/** Table twin for ChartCard: one row per year, months as columns. */
export function calendarTable(
  cells: CalendarCell[],
  format: (v: number) => string,
  yearTotals?: Record<number, number | null>,
): { columns: string[]; rows: (string | number)[][] } {
  const byKey = new Map(cells.map((c) => [`${c.year}-${c.month}`, c]));
  const show = (v: number | null | undefined) => (v === null || v === undefined ? "—" : withSign(v, format));
  return {
    columns: ["Year", ...MONTHS, "Year total"],
    rows: years(cells).map((y) => [
      String(y),
      ...MONTHS.map((_, i) => show(byKey.get(`${y}-${i + 1}`)?.value)),
      show(yearTotals?.[y]),
    ]),
  };
}

export function CalendarHeatmap({ cells, format, yearTotals }: CalendarHeatmapProps) {
  const t = useChartTheme();
  const byKey = new Map(cells.map((c) => [`${c.year}-${c.month}`, c]));
  const vmax = Math.max(0, ...cells.map((c) => (c.value === null ? 0 : Math.abs(c.value))));
  const grid = "grid grid-cols-[40px_repeat(12,minmax(0,1fr))_56px] gap-0.5";

  const cell = (v: number | null | undefined, tip: string, extra?: string) =>
    v === null || v === undefined ? (
      <div className={clsx("flex h-8 items-center justify-center rounded-sm bg-surface-2 text-xs text-ink-3", extra)} title={tip}>
        ·
      </div>
    ) : (
      <div
        className={clsx("nums flex h-8 items-center justify-center rounded-sm text-xs text-ink", extra)}
        style={{ background: tint(v, vmax, t) }}
        title={tip}
      >
        {withSign(v, format)}
      </div>
    );

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[600px]">
        <div className={clsx(grid, "mb-0.5 text-2xs text-ink-3")}>
          <span />
          {MONTHS.map((m) => (
            <span key={m} className="text-center">
              {m}
            </span>
          ))}
          <span className="text-center">Year</span>
        </div>
        {years(cells).map((y) => (
          <div key={y} className={clsx(grid, "mb-0.5")}>
            <span className="nums flex items-center text-xs text-ink-2">{y}</span>
            {MONTHS.map((m, i) => {
              const c = byKey.get(`${y}-${i + 1}`);
              const v = c?.value;
              const tip = `${m} ${y} · ${v === null || v === undefined ? "no data" : withSign(v, format)}${c?.partial ? " · month to date" : ""}`;
              return (
                <div key={m}>
                  {cell(v, tip, c?.partial ? "outline-dashed outline-1 -outline-offset-1 outline-ink-3" : undefined)}
                </div>
              );
            })}
            {cell(yearTotals?.[y], `${y} total`, "font-semibold")}
          </div>
        ))}
        {vmax > 0 && (
          <div className="mt-2 inline-flex flex-col gap-0.5 text-2xs text-ink-3">
            <span className="flex gap-0.5">
              {[-1, -0.5, 0, 0.5, 1].map((k) => (
                <span key={k} className="h-2.5 w-8 rounded-sm" style={{ background: tint(k * vmax, vmax, t) }} />
              ))}
            </span>
            <span className="nums flex justify-between gap-2">
              <span>{withSign(-vmax, format)}</span>
              <span>0</span>
              <span>{withSign(vmax, format)}</span>
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 1DF0D05D0AB4 - verify with scripts/authorship.py verify
