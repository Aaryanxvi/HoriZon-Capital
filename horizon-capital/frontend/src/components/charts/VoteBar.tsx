// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-35C7B92E9B5F
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { StatusChip } from "@/components/ui";
import { useChartTheme, type ChartTheme } from "@/lib/colors";
import { useWidth } from "./Tooltip";

export interface VoteBarProps {
  against: number;
  abstain: number;
  for_: number;
  error?: number;
  height?: number;
}

// Relative luminance → pick the darker or lighter text token for a label set inside a fill.
function inkOn(hex: string, t: ChartTheme): string {
  const n = parseInt(hex.slice(1), 16);
  const lin = (c: number) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const l = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  const [dark, light] = t.mode === "dark" ? [t.surface, t.text] : [t.text, t.surface];
  return l > 0.18 ? dark : light;
}

export function VoteBar({ against, abstain, for_, error = 0, height = 10 }: VoteBarProps) {
  const t = useChartTheme();
  const [box, width] = useWidth<HTMLDivElement>();
  const segments = [
    { key: "against", label: "Against", n: against, color: t.status.critical },
    { key: "abstain", label: "Abstain", n: abstain, color: t.border },
    { key: "for", label: "For", n: for_, color: t.status.ok },
  ];
  const total = against + abstain + for_;
  const live = segments.filter((s) => s.n > 0);
  const usable = width - 2 * Math.max(0, live.length - 1); // 2px surface gaps
  const aria = `Votes: ${against} against, ${abstain} abstain, ${for_} for${error ? `, ${error} errors` : ""}`;

  return (
    <div>
      <div
        ref={box}
        role="img"
        aria-label={aria}
        className="flex gap-0.5 overflow-hidden rounded-[3px] bg-surface-2"
        style={{ height }}
      >
        {live.map((s) => {
          // Count inside only when it fits: ≥ 24px wide and tall enough for 11px text.
          const fits = height >= 16 && (s.n / total) * usable >= 24;
          return (
            <div
              key={s.key}
              className="nums flex min-w-0 items-center justify-center text-2xs font-medium"
              style={{ flex: `${s.n} 1 0px`, background: s.color, color: inkOn(s.color, t) }}
              title={`${s.label}: ${s.n}`}
            >
              {fits ? s.n : null}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
        {segments.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.label}
            <span className="nums text-ink">{s.n}</span>
          </span>
        ))}
        {error > 0 && <StatusChip tone="warning" label={`${error} error${error === 1 ? "" : "s"}`} />}
      </div>
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 35C7B92E9B5F - verify with scripts/authorship.py verify
