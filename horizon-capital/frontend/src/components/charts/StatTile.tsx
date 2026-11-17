// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-DEC74EE3805F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import type { ReactNode } from "react";
import { StatusChip } from "@/components/ui";
import { Sparkline } from "./Sparkline";
import { withSign } from "./Tooltip";

export interface StatTileProps {
  label: string;
  value: ReactNode;
  /** `upIsGood: false` flips the colour mapping (drawdown, VaR); the glyph always follows the sign. */
  delta?: { value: number; format: (v: number) => string; upIsGood?: boolean; label?: string };
  trend?: number[];
  status?: { tone: "ok" | "warning" | "serious" | "critical"; label: string };
  hint?: ReactNode;
  className?: string;
}

export function StatTile({ label, value, delta, trend, status, hint, className }: StatTileProps) {
  const hasTrend = !!trend && trend.filter(Number.isFinite).length >= 2;
  return (
    <div className={clsx("card relative min-h-[84px] px-3 py-2.5", className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="truncate text-2xs font-medium uppercase tracking-wide text-ink-3">{label}</div>
        {status && <StatusChip tone={status.tone} label={status.label} />}
      </div>
      {/* Proportional figures on purpose — tabular digits look loose at this size. */}
      <div className="mt-1 text-[22px] font-semibold leading-7 text-ink">{value}</div>
      <div className={clsx(hasTrend && "pr-[104px]")}>
        {delta && <Delta {...delta} />}
        {hint !== undefined && <div className="mt-0.5 truncate text-xs text-ink-3">{hint}</div>}
      </div>
      {hasTrend && (
        <div className="absolute bottom-2.5 right-3">
          <Sparkline data={trend!} tone="neutral" title={`${label} trend`} />
        </div>
      )}
    </div>
  );
}

function Delta({ value, format, upIsGood = true, label }: NonNullable<StatTileProps["delta"]>) {
  if (value === 0 || !Number.isFinite(value)) {
    return (
      <div className="mt-0.5 text-xs text-ink-3">
        — flat{label && <span className="ml-1">{label}</span>}
      </div>
    );
  }
  const good = upIsGood ? value > 0 : value < 0;
  return (
    <div className="mt-0.5 flex items-baseline gap-1 text-xs">
      <span className={good ? "text-up" : "text-down"}>
        {value > 0 ? "▲" : "▼"} {withSign(value, format)}
      </span>
      {label && <span className="text-ink-3">{label}</span>}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token DEC74EE3805F - verify with scripts/authorship.py verify
