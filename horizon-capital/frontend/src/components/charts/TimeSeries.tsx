// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-E5BD10E8362B
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { lwChartOptions, useChartTheme, withAlpha, type ChartTheme } from "@/lib/colors";
import { dateTime, num } from "@/lib/format";
import { Tooltip } from "./Tooltip";

/** "YYYY-MM-DD" for daily (business day), unix seconds for intraday. `color` colours one histogram bar. */
export type TSPoint = { time: string | number; value: number; color?: string };

export type TSSeries = {
  id: string;
  label: string;
  kind: "line" | "area" | "histogram" | "baseline";
  data: TSPoint[];
  color?: string;
  fillColor?: string;
  lineWidth?: 1 | 2;
  priceScaleId?: string;
  scaleMargins?: { top: number; bottom: number };
  baseValue?: number;
  upColor?: string;
  downColor?: string;
  format?: (v: number) => string;
  markers?: SeriesMarker<Time>[];
};

export type CrosshairReadout = { time: string | number | null; values: Record<string, number | null> };

export interface TimeSeriesProps {
  /** Memoize the `data` arrays: a new array reference means setData. */
  series: TSSeries[];
  height: number;
  syncKey?: string;
  fitContent?: boolean;
  timeVisible?: boolean;
  priceFormatter?: (v: number) => string;
  /** Values at the hovered time; the LAST value of each series at rest (time = null). */
  onCrosshair?: (r: CrosshairReadout) => void;
  /** Default true: point markers on line/area series with ≤ 30 points. */
  pointMarkersWhenSparse?: boolean;
}

type Rec = {
  api: ISeriesApi<SeriesType>;
  kind: TSSeries["kind"];
  data: TSPoint[] | null; // the input array last pushed, compared by reference
  byTime: Map<string, number>;
  last: number | null;
};

type Peer = { chart: IChartApi; showAt: (time: Time | null) => void };

// Charts sharing a syncKey mirror visible range and crosshair. `syncing` guards
// re-entry while one chart pushes to its peers.
const registry = new Map<string, Set<Peer>>();
let syncing = false;

function broadcast(key: string | undefined, self: Peer, fn: (peer: Peer) => void) {
  if (!key || syncing) return;
  syncing = true;
  try {
    registry.get(key)?.forEach((peer) => peer !== self && fn(peer));
  } finally {
    syncing = false;
  }
}

// lightweight-charts asserts strictly ascending times and finite values.
function tidy(data: TSPoint[]) {
  const sorted = data
    .filter((p) => Number.isFinite(p.value))
    .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  const out: TSPoint[] = [];
  for (const p of sorted) {
    if (out.length && out[out.length - 1].time === p.time) out[out.length - 1] = p;
    else out.push(p);
  }
  return out;
}

function addSeries(chart: IChartApi, kind: TSSeries["kind"]): ISeriesApi<SeriesType> {
  switch (kind) {
    case "area":
      return chart.addAreaSeries();
    case "histogram":
      return chart.addHistogramSeries();
    case "baseline":
      return chart.addBaselineSeries();
    default:
      return chart.addLineSeries();
  }
}

function seriesOptions(
  s: TSSeries,
  t: ChartTheme,
  markers: boolean,
  format: ((v: number) => string) | undefined,
) {
  const color = s.color ?? t.series[0];
  const common = {
    priceScaleId: s.priceScaleId,
    priceLineVisible: false, // the price line is dashed; the grid stays solid
    ...(format ? { priceFormat: { type: "custom" as const, formatter: format, minMove: 1e-6 } } : {}),
  };
  const marker = {
    pointMarkersVisible: markers,
    pointMarkersRadius: 4,
    crosshairMarkerRadius: 4,
    crosshairMarkerBorderColor: t.surface,
    crosshairMarkerBorderWidth: 2,
  };
  const lineWidth = s.lineWidth ?? 2;
  switch (s.kind) {
    case "area":
      return {
        ...common,
        ...marker,
        lineColor: color,
        lineWidth,
        topColor: s.fillColor ?? withAlpha(color, 0.12),
        bottomColor: withAlpha(color, 0),
      };
    case "histogram":
      return { ...common, color, base: s.baseValue ?? 0 };
    case "baseline": {
      const up = s.upColor ?? t.up;
      const down = s.downColor ?? t.down;
      return {
        ...common,
        lineWidth,
        baseValue: { type: "price" as const, price: s.baseValue ?? 0 },
        topLineColor: up,
        topFillColor1: withAlpha(up, 0.12),
        topFillColor2: withAlpha(up, 0),
        bottomLineColor: down,
        bottomFillColor1: withAlpha(down, 0),
        bottomFillColor2: withAlpha(down, 0.12),
        crosshairMarkerBorderColor: t.surface,
        crosshairMarkerBorderWidth: 2,
      };
    }
    default:
      return { ...common, ...marker, color, lineWidth };
  }
}

function timeLabel(time: Time): string {
  if (typeof time === "number") return dateTime(new Date(time * 1000).toISOString());
  if (typeof time === "string") {
    return new Date(`${time}T00:00:00Z`).toLocaleDateString("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
  return `${time.year}-${time.month}-${time.day}`;
}

export function TimeSeries({
  series,
  height,
  syncKey,
  fitContent,
  timeVisible,
  priceFormatter,
  onCrosshair,
  pointMarkersWhenSparse = true,
}: TimeSeriesProps) {
  const theme = useChartTheme();
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const peerRef = useRef<Peer | null>(null);
  const records = useRef(new Map<string, Rec>());
  const fitted = useRef(false);
  // A fit taken while the container is 0 wide freezes a sub-pixel bar spacing that a later
  // resize keeps, so the fit waits here until the box has a real width.
  const needsFit = useRef(false);
  const hovering = useRef(false);
  const lastEmit = useRef("");
  const props = useRef({ series, syncKey, onCrosshair });
  props.current = { series, syncKey, onCrosshair };
  const [tip, setTip] = useState<{ x: number; y: number; time: Time } | null>(null);

  // Readout for `time`, or the last value of each series when time is null. Deduped
  // so a parent that re-renders from this callback cannot loop.
  const emit = (time: Time | null) => {
    const cb = props.current.onCrosshair;
    if (!cb) return;
    const values: Record<string, number | null> = {};
    for (const s of props.current.series) {
      const rec = records.current.get(s.id);
      values[s.id] = !rec ? null : time === null ? rec.last : rec.byTime.get(String(time)) ?? null;
    }
    const out = { time: time === null ? null : (time as string | number), values };
    const key = JSON.stringify(out);
    if (key === lastEmit.current) return;
    lastEmit.current = key;
    cb(out);
  };
  const emitRef = useRef(emit);
  emitRef.current = emit;

  // Create once per mount; everything else is applyOptions/setData below.
  useEffect(() => {
    const el = box.current!;
    const chart = createChart(el, { ...lwChartOptions(theme), width: el.clientWidth, height });
    chartRef.current = chart;

    const peer: Peer = {
      chart,
      showAt: (time) => {
        for (const rec of records.current.values()) {
          const value = time === null ? undefined : rec.byTime.get(String(time));
          if (value !== undefined) {
            try {
              chart.setCrosshairPosition(value, time!, rec.api);
            } catch {
              // throws when the peer has nothing visible to anchor the price to
              chart.clearCrosshairPosition();
            }
            emitRef.current(time);
            return;
          }
        }
        chart.clearCrosshairPosition();
        emitRef.current(null);
      },
    };
    peerRef.current = peer;

    const onMove = (p: MouseEventParams<Time>) => {
      const time = p.point && p.time !== undefined ? p.time : null;
      hovering.current = time !== null;
      setTip(time !== null && p.point ? { x: p.point.x, y: p.point.y, time } : null);
      emitRef.current(time);
      broadcast(props.current.syncKey, peer, (q) => q.showAt(time));
    };
    // Only pan/zoom the user did is mirrored. Each pane fits its own data on load; mirroring
    // those programmatic ranges let a peer's pre-fit default (≈190 bars) overwrite the fit,
    // so long series (a 4-year backtest) showed only their last months.
    let touchedAt = 0;
    const touch = (e: Event) => {
      if (e.type !== "pointermove" || (e as PointerEvent).buttons) touchedAt = Date.now();
    };
    const INPUTS = ["pointerdown", "pointermove", "wheel", "touchstart", "keydown"] as const;
    INPUTS.forEach((t) => el.addEventListener(t, touch, { passive: true }));
    const onRange = (range: LogicalRange | null) => {
      if (range && Date.now() - touchedAt < 500)
        broadcast(props.current.syncKey, peer, (q) => q.chart.timeScale().setVisibleLogicalRange(range));
    };
    chart.subscribeCrosshairMove(onMove);
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);

    const ro = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width);
      chart.applyOptions({ width });
      if (width > 0 && needsFit.current) {
        needsFit.current = false;
        chart.timeScale().fitContent();
      }
    });
    ro.observe(el);

    const recs = records.current;
    return () => {
      ro.disconnect();
      INPUTS.forEach((t) => el.removeEventListener(t, touch));
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      chart.remove();
      chartRef.current = null;
      peerRef.current = null;
      recs.clear();
      fitted.current = false;
      needsFit.current = false;
      lastEmit.current = "";
    };
    // Theme/height changes are applied by the sync effect, never by recreating the chart.
  }, []);

  useEffect(() => {
    const peer = peerRef.current;
    if (!syncKey || !peer) return;
    const peers = registry.get(syncKey) ?? new Set<Peer>();
    registry.set(syncKey, peers);
    peers.add(peer);
    return () => {
      peers.delete(peer);
      if (!peers.size) registry.delete(syncKey);
    };
  }, [syncKey]);

  // Options, series and data. Idempotent: safe to run on every relevant change.
  useEffect(() => {
    const chart = chartRef.current;
    const el = box.current;
    if (!chart || !el) return;
    const base = lwChartOptions(theme);
    chart.applyOptions({
      ...base,
      height,
      timeScale: { ...base.timeScale, timeVisible: !!timeVisible, secondsVisible: false },
    });

    const recs = records.current;
    const seen = new Set<string>();
    let dataChanged = false;
    for (const s of series) {
      seen.add(s.id);
      let rec = recs.get(s.id);
      if (rec && rec.kind !== s.kind) {
        chart.removeSeries(rec.api);
        rec = undefined;
      }
      if (!rec) {
        rec = { api: addSeries(chart, s.kind), kind: s.kind, data: null, byTime: new Map(), last: null };
        recs.set(s.id, rec);
      }
      if (rec.data !== s.data) {
        const points = tidy(s.data);
        rec.api.setData(points.map((p) => ({ ...p, time: p.time as Time })));
        rec.data = s.data;
        rec.byTime = new Map(points.map((p) => [String(p.time), p.value]));
        rec.last = points.length ? points[points.length - 1].value : null;
        dataChanged = true;
      }
      rec.api.applyOptions(
        seriesOptions(s, theme, pointMarkersWhenSparse && rec.byTime.size <= 30, s.format ?? priceFormatter),
      );
      rec.api.setMarkers(s.markers ?? []);
      if (s.scaleMargins) {
        // top ≥ 0.15 keeps the highest tick label unclipped; the sum must stay ≤ 1.
        const top = Math.max(s.scaleMargins.top, 0.15);
        const bottom = Math.min(s.scaleMargins.bottom, 1 - top);
        chart.priceScale(s.priceScaleId ?? "right").applyOptions({ scaleMargins: { top, bottom } });
      }
    }
    for (const [id, rec] of recs) {
      if (!seen.has(id)) {
        chart.removeSeries(rec.api);
        recs.delete(id);
      }
    }
    const hasData = [...recs.values()].some((r) => r.byTime.size > 0);
    if (dataChanged && hasData && (fitContent || !fitted.current)) {
      needsFit.current = true;
      fitted.current = true;
    }
    const width = el.clientWidth;
    if (needsFit.current && width > 0) {
      needsFit.current = false;
      chart.applyOptions({ width }); // the ResizeObserver may not have delivered it yet
      chart.timeScale().fitContent();
    }
    if (!hovering.current) emitRef.current(null);
  }, [series, theme, height, timeVisible, priceFormatter, pointMarkersWhenSparse, fitContent]);

  const readout = tip
    ? series.map((s) => {
        const value = records.current.get(s.id)?.byTime.get(String(tip.time));
        const fmt = s.format ?? priceFormatter ?? ((v: number) => num(v));
        return {
          value: value === undefined ? "—" : fmt(value),
          label: s.label,
          color: s.kind === "baseline" ? s.upColor ?? theme.up : s.color ?? theme.series[0],
        };
      })
    : null;

  return (
    <div className="relative" style={{ height }}>
      <div
        ref={box}
        className="absolute inset-0"
        role="img"
        aria-label={`${series.map((s) => s.label).join(", ")} over time`}
      />
      {tip && readout && (
        <Tooltip
          x={tip.x}
          y={tip.y}
          width={box.current?.clientWidth ?? 0}
          title={timeLabel(tip.time)}
          rows={readout}
        />
      )}
    </div>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token E5BD10E8362B - verify with scripts/authorship.py verify
