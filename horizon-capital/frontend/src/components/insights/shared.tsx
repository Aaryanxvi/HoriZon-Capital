import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { StatTile } from "@/components/charts";
import { Card, ErrorNote, Loading } from "@/components/ui";
import type { Gated } from "@/lib/insights-api";
import { num } from "@/lib/format";

/** Loading / error frame shared by every insight tab. */
export function TabFrame<T>({
  q,
  label,
  children,
}: {
  q: UseQueryResult<T>;
  label: string;
  children: (data: T) => ReactNode;
}) {
  if (q.isLoading) {
    return (
      <Card>
        <Loading label={`Loading ${label}`} />
      </Card>
    );
  }
  if (q.error || !q.data) return <ErrorNote message={q.error?.message ?? `No ${label} data`} />;
  return <div className="space-y-3">{children(q.data)}</div>;
}

/** "3 of 30 days needed" when withheld, else the sample it rests on. */
export function sampleNote(g: Gated, unit: string): string {
  return g.value === null ? `${g.n} of ${g.min} ${unit} needed` : `n = ${g.n} ${unit}`;
}

/** Stat tile for a gated metric: "—" plus the shortfall below its minimum sample. */
export function GateTile({
  label,
  g,
  format,
  unit,
}: {
  label: string;
  g: Gated;
  format: (v: number) => string;
  unit: string;
}) {
  return <StatTile label={label} value={g.value === null ? "—" : format(g.value)} hint={sampleNote(g, unit)} />;
}

export const pctOf = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "—" : `${num(v * 100, digits)}%`;

/** Seconds → "45s" / "12m" / "3.5h" / "23d". */
export function age(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86_400) return `${num(s / 3600, 1)}h`;
  return `${Math.round(s / 86_400)}d`;
}

/** Table cell: right-aligned figure, "—" when missing (with why on hover). */
export function NumCell({ children, why }: { children: ReactNode; why?: string }) {
  return (
    <td className="td nums text-right" title={children === "—" ? why : undefined}>
      {children}
    </td>
  );
}
