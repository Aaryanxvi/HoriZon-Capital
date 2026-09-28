// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-36FCB3C41FB5
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useEffect, useState } from "react";

// Recharts writes colours into SVG presentation attributes, where `var(--x)` is
// never resolved — the shape draws with no visible stroke. So read the variables
// once from the document and hand real rgb() strings to the charts.
const TOKENS = ["clay", "up", "down", "warn", "line", "faint", "surface", "ink"] as const;

export type ChartColors = Record<(typeof TOKENS)[number], string> & { series: string[] };

function read(): ChartColors {
  const style = getComputedStyle(document.documentElement);
  const resolved = Object.fromEntries(
    TOKENS.map((token) => [token, `rgb(${style.getPropertyValue(`--${token}`).trim()})`]),
  ) as Record<(typeof TOKENS)[number], string>;

  return {
    ...resolved,
    series: [
      resolved.clay,
      resolved.up,
      resolved.warn,
      "#6b8afd",
      "#a78bfa",
      "#3fb6c4",
      "#e0779b",
    ],
  };
}

/** Chart palette that follows the light/dark toggle. */
export function useChartColors(): ChartColors {
  const [colors, setColors] = useState<ChartColors>(read);

  useEffect(() => {
    const observer = new MutationObserver(() => setColors(read()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return colors;
}

/** Shared tooltip styling — same surface and border as the cards. */
export function tooltipStyle(colors: ChartColors) {
  return {
    background: colors.surface,
    border: `1px solid ${colors.line}`,
    borderRadius: 8,
    fontSize: 12,
    color: colors.ink,
  };
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 36FCB3C41FB5 - verify with scripts/authorship.py verify
