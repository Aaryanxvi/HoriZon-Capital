// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-AD3BF8F7A7D7
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { Table2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Empty, ErrorNote, IconButton, Loading } from "@/components/ui";

export type LegendItem = { label: string; color: string; shape?: "line" | "rect" | "dot"; value?: string };

export interface ChartCardProps {
  title: string;
  subtitle?: ReactNode;
  /** Rendered only for ≥ 2 items — a single series is named by the title. */
  legend?: LegendItem[];
  toolbar?: ReactNode;
  /** The chart's table twin (WCAG equivalent), toggled from the header. */
  table?: { columns: string[]; rows: (string | number)[][] };
  isLoading?: boolean;
  isFetching?: boolean;
  error?: string | null;
  empty?: { message: string; hint?: string } | null;
  height?: number;
  className?: string;
  children: ReactNode;
}

// "+1.2%", "$1,234", "−0.5 pp", "1.25×" → right-aligned tabular column. Dates stay left.
const NUMERIC = /^[+\-−]?\s*[$₹€£]?\s*[\d.,]+\s*(%|×|x|pp|bps|[KMB])?$/;
const BLANK = new Set(["", "—", "-", "·"]);

function isNumericColumn(rows: (string | number)[][], col: number): boolean {
  let any = false;
  for (const row of rows) {
    const cell = row[col];
    if (typeof cell === "number") any = true;
    else if (cell === undefined || BLANK.has(cell.trim())) continue;
    else if (NUMERIC.test(cell.trim())) any = true;
    else return false;
  }
  return any;
}

function Swatch({ color, shape = "line" }: { color: string; shape?: LegendItem["shape"] }) {
  if (shape === "rect") return <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: color }} />;
  if (shape === "dot") return <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />;
  return <span className="h-[3px] w-2.5 shrink-0 rounded-full" style={{ background: color }} />;
}

export function ChartCard({
  title,
  subtitle,
  legend,
  toolbar,
  table,
  isLoading,
  isFetching,
  error,
  empty,
  height,
  className,
  children,
}: ChartCardProps) {
  const [showTable, setShowTable] = useState(false);
  const state = error ? (
    <div className="p-3">
      <ErrorNote message={error} />
    </div>
  ) : isLoading ? (
    <Loading />
  ) : empty ? (
    <Empty message={empty.message} hint={empty.hint} />
  ) : null;
  const tableMode = !state && showTable && !!table;
  const numeric = table ? table.columns.map((_, i) => isNumericColumn(table.rows, i)) : [];

  return (
    <section className={clsx("card flex flex-col", className)}>
      <header className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-line px-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
          {subtitle && <span className="truncate text-xs text-ink-3">{subtitle}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {toolbar}
          {table && (
            <IconButton
              label={showTable ? "Show chart" : "Show table"}
              icon={Table2}
              pressed={showTable}
              onClick={() => setShowTable((v) => !v)}
            />
          )}
        </div>
      </header>
      {!state && !tableMode && legend && legend.length >= 2 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pt-2 text-xs">
          {legend.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <Swatch color={item.color} shape={item.shape} />
              <span className="text-ink-2">{item.label}</span>
              {item.value !== undefined && <span className="nums text-ink">{item.value}</span>}
            </span>
          ))}
        </div>
      )}
      <div
        className={clsx(
          "flex-1 transition-opacity duration-150",
          isFetching && "opacity-60",
          state && "flex flex-col justify-center",
          !state && !tableMode && "p-3",
        )}
        style={state && height ? { minHeight: height } : undefined}
      >
        {state ??
          (tableMode ? (
            <div className="overflow-auto" style={{ maxHeight: height }}>
              <table className="w-full border-collapse text-sm">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line">
                    {table.columns.map((c, i) => (
                      <th
                        key={i}
                        scope="col"
                        className={clsx(
                          "whitespace-nowrap px-3 py-1.5 text-2xs font-medium uppercase tracking-wide text-ink-3",
                          numeric[i] ? "text-right" : "text-left",
                        )}
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, r) => (
                    <tr key={r} className="border-b border-line last:border-0">
                      {row.map((cell, i) => (
                        <td
                          key={i}
                          className={clsx("whitespace-nowrap px-3 py-1.5 text-ink", numeric[i] && "nums text-right")}
                        >
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            children
          ))}
      </div>
    </section>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token AD3BF8F7A7D7 - verify with scripts/authorship.py verify
