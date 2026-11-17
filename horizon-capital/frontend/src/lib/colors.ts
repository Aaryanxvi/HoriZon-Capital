// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-36FCB3C41FB5
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useSyncExternalStore } from "react";
import { ColorType, CrosshairMode, LineStyle, type ChartOptions, type DeepPartial } from "lightweight-charts";

// Tokens live in index.css as "r g b" triplets. Canvas charts (lightweight-charts)
// reject the space syntax and SVG presentation attributes never resolve var(--x),
// so every colour handed to a chart is resolved here to a real #rrggbb string.

export interface ChartTheme {
  mode: "light" | "dark";
  surface: string;
  canvas: string;
  surface2: string;
  text: string;
  text2: string;
  text3: string;
  grid: string;
  border: string;
  crosshair: string;
  accent: string;
  accentStrong: string;
  up: string;
  down: string;
  upFill: string;
  downFill: string;
  accentFill: string;
  neutral: string;
  divergingMid: string;
  series: string[];
  sequential: string[];
  status: { ok: string; warning: string; serious: string; critical: string };
}

// Validated palettes (spec §2) — fixed order, never cycled.
const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const SEQUENTIAL_LIGHT = [
  "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
  "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
];
const SEQUENTIAL_DARK = [...SEQUENTIAL_LIGHT].reverse();

export const CHART_FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** "#rrggbb" + alpha → "rgba(r, g, b, a)" (comma syntax, which canvas accepts). */
export function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

export function readChartTheme(): ChartTheme {
  const root = document.documentElement;
  const attr = root.getAttribute("data-theme");
  const mode =
    attr === "dark" || (attr !== "light" && window.matchMedia(DARK_QUERY).matches) ? "dark" : "light";
  const style = getComputedStyle(root);
  const token = (name: string) => {
    const rgb = style.getPropertyValue(`--${name}`).trim().split(/\s+/).map(Number);
    // A missing token must not reach the canvas parser (it throws on bad colours).
    if (rgb.length !== 3 || rgb.some(Number.isNaN)) return "#808080";
    return "#" + rgb.map((c) => c.toString(16).padStart(2, "0")).join("");
  };

  const accent = token("accent");
  const up = token("up");
  const down = token("down");
  const ink3 = token("ink-3");
  return {
    mode,
    surface: token("surface"),
    canvas: token("canvas"),
    surface2: token("surface-2"),
    text: token("ink"),
    text2: token("ink-2"),
    text3: ink3,
    grid: token("line"),
    border: token("line-strong"),
    crosshair: ink3,
    accent,
    accentStrong: token("accent-strong"),
    up,
    down,
    upFill: withAlpha(up, 0.12),
    downFill: withAlpha(down, 0.12),
    accentFill: withAlpha(accent, 0.12),
    neutral: ink3,
    divergingMid: mode === "dark" ? "#2a2f37" : "#eceff3",
    series: mode === "dark" ? SERIES_DARK : SERIES_LIGHT,
    sequential: mode === "dark" ? SEQUENTIAL_DARK : SEQUENTIAL_LIGHT,
    status: {
      ok: token("ok"),
      warning: token("warn"),
      serious: token("serious"),
      critical: token("crit"),
    },
  };
}

// One shared snapshot for every chart: re-read only when the theme attribute or
// the OS scheme changes. ponytail: observers stay attached for the page lifetime
// (one document, one app) instead of ref-counting subscribers.
let snapshot: ChartTheme | null = null;
let attached = false;
const listeners = new Set<() => void>();

function refresh() {
  snapshot = readChartTheme();
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void) {
  if (!attached) {
    attached = true;
    new MutationObserver(refresh).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    window.matchMedia(DARK_QUERY).addEventListener("change", refresh);
  }
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function getSnapshot(): ChartTheme {
  return (snapshot ??= readChartTheme());
}

/** Resolved chart palette; a new object only when the theme actually changes. */
export function useChartTheme(): ChartTheme {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** Base lightweight-charts options for the current theme. */
export function lwChartOptions(t: ChartTheme): DeepPartial<ChartOptions> {
  const crosshairLine = {
    width: 1 as const,
    style: LineStyle.Solid,
    color: t.crosshair,
    // Label text is picked by luminance; light ink in dark mode would wash out.
    labelBackgroundColor: t.mode === "dark" ? t.accentStrong : t.text,
  };
  return {
    layout: {
      background: { type: ColorType.Solid, color: t.surface },
      textColor: t.text3,
      fontFamily: CHART_FONT,
      fontSize: 11,
      // The license attribution lives on the Settings page instead of on every chart.
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: t.grid, style: LineStyle.Solid },
      horzLines: { color: t.grid, style: LineStyle.Solid },
    },
    crosshair: { mode: CrosshairMode.Normal, vertLine: crosshairLine, horzLine: crosshairLine },
    // Top margin keeps the highest tick label clear of the plot edge.
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.08 } },
    timeScale: { borderVisible: false, rightOffset: 2, fixLeftEdge: true },
    handleScroll: true,
    handleScale: true,
    localization: { locale: "en-US" },
  };
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 36FCB3C41FB5 - verify with scripts/authorship.py verify
