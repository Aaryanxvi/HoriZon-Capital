// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-F3946D9390B0
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { StatusChip } from "@/components/ui";
import { useChartTheme, withAlpha } from "@/lib/colors";

export interface BulletProps {
  label: string;
  value: number;
  limit: number | null;
  format: (v: number) => string;
  warnAt?: number;
  seriousAt?: number;
  note?: string;
}

export type LimitStatus = { tone: "ok" | "warning" | "serious" | "critical"; label: string };

const SPAN = 1.25; // the track runs to 1.25 × limit so a breach visibly passes the marker

/** Usage vs limit → status. Shared so a KPI tile can wear the same chip as its gauge. */
export function limitStatus(value: number, limit: number, warnAt = 0.6, seriousAt = 0.85): LimitStatus {
  const ratio = limit > 0 ? value / limit : value > 0 ? Infinity : 0;
  if (ratio >= 1) return { tone: "critical", label: "Breach" };
  if (ratio >= seriousAt) return { tone: "serious", label: "Near limit" };
  if (ratio >= warnAt) return { tone: "warning", label: "Elevated" };
  return { tone: "ok", label: "OK" };
}

export function Bullet({ label, value, limit, format, warnAt = 0.6, seriousAt = 0.85, note }: BulletProps) {
  const t = useChartTheme();
  const status = limit === null ? null : limitStatus(value, limit, warnAt, seriousAt);
  // No (or zero) limit → nothing to scale against: full bar when there is any usage.
  const ratio = limit !== null && limit > 0 ? value / limit : value > 0 ? SPAN : 0;
  const fill = Math.min(Math.max(ratio, 0), SPAN) / SPAN;
  const color = status ? t.status[status.tone] : t.neutral;
  const max = limit === null ? Math.max(value, 0) : limit * SPAN;
  const exact = `${label}: ${format(value)} of ${limit === null ? "no limit set" : `${format(limit)} limit`}`;

  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuenow={Math.min(Math.max(value, 0), max)}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuetext={exact}
      title={exact}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-sm text-ink-2">{label}</span>
        {status && <StatusChip tone={status.tone} label={status.label} />}
      </div>
      <div className="mt-0.5 flex items-baseline justify-between gap-2">
        <span className="nums shrink-0 text-sm text-ink">
          {format(value)} / {limit === null ? "—" : format(limit)}
        </span>
        {note && <span className="min-w-0 truncate text-2xs text-ink-3">{note}</span>}
      </div>
      <div
        className="relative mt-1.5 h-2 rounded"
        style={{ background: status ? withAlpha(color, 0.15) : t.surface2 }}
      >
        <div className="h-2 rounded" style={{ width: `${fill * 100}%`, background: color }} />
        {limit !== null && (
          <div
            className="absolute top-1/2 h-3.5 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-ink"
            style={{ left: `${100 / SPAN}%` }}
          />
        )}
      </div>
      <div className="relative mt-1 h-3.5 text-2xs text-ink-3">
        {limit === null ? (
          "no limit set"
        ) : (
          <span className="absolute -translate-x-1/2" style={{ left: `${100 / SPAN}%` }}>
            limit
          </span>
        )}
      </div>
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token F3946D9390B0 - verify with scripts/authorship.py verify
