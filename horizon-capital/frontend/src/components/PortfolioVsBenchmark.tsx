// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-3540BC28B48B
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import { useMemo, useState } from "react";
import {
  ChartCard,
  TimeSeries,
  type CrosshairReadout,
  type LegendItem,
  type TSPoint,
  type TSSeries,
} from "@/components/charts";
import { Segmented } from "@/components/ui";
import { ApiError, useEquityCurve } from "@/lib/api";
import { useChartTheme } from "@/lib/colors";
import { dateTime, money } from "@/lib/format";
import {
  alignByDate,
  drawdown,
  indexTo100,
  rangeStart,
  type DatedValue,
  type RangeKey as DailyRange,
} from "@/lib/series";
import { useBenchmark, useNavDaily, type BenchmarkRange } from "@/lib/viz-api";

/** "1D" is the intraday NAV view; every other range is daily and benchmarked. */
export type RangeKey = "1D" | DailyRange;

export interface PortfolioVsBenchmarkProps {
  syncKey: string;
  defaultRange?: RangeKey;
  height?: number;
  /** Drives the range from outside (Performance's period filter) and hides the range toolbar. */
  rangeOverride?: RangeKey | null;
  className?: string;
}

const RANGES: RangeKey[] = ["1D", "1W", "1M", "3M", "YTD", "1Y", "ALL"];
const RANGE_OPTIONS = RANGES.map((r) => ({ value: r, label: r }));
// Smallest benchmark window covering each chart range ("1D" plots no benchmark).
const BENCH_RANGE: Record<RangeKey, BenchmarkRange> = {
  "1D": "1M",
  "1W": "1M",
  "1M": "1M",
  "3M": "6M",
  YTD: "1Y",
  "1Y": "1Y",
  ALL: "5Y",
};
// Below this many daily points the axis zooms into noise and the chart reads as broken.
const MIN_DAYS = 5;
const STORAGE_KEY = "horizon-range";
const DD_HEIGHT = 90;

function storedRange(fallback: RangeKey): RangeKey {
  try {
    const v = localStorage.getItem(STORAGE_KEY) as RangeKey | null;
    return v && RANGES.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

const idx = (v: number) => v.toFixed(2);
const idxOrDash = (v: number | null | undefined) => (v === null || v === undefined ? "—" : idx(v));

/** Drawdown fraction (≤ 0) → "−1.2%". */
function ddPct(v: number): string {
  const text = Math.abs(v * 100).toFixed(1);
  return text === "0.0" ? "0.0%" : `−${text}%`;
}

// Snapshot timestamps look like "2026-08-30 17:11:38.363417+00:00"; bare ones are UTC.
function unix(ts: string): number {
  const iso = ts.replace(" ", "T");
  return Math.floor(Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`) / 1000);
}

const unixLabel = (s: number) => dateTime(new Date(s * 1000).toISOString());

function failure(endpoint: string, e: unknown): string {
  const why = e instanceof ApiError ? `HTTP ${e.status}` : e instanceof Error ? e.message : "request failed";
  return `GET ${endpoint} failed (${why})`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const toTS = (pts: DatedValue[]): TSPoint[] => pts.map((p) => ({ time: p.date, value: p.value }));

/** "Portfolio vs SPY, indexed to 100" with a synced drawdown pane; "1D" = intraday NAV only. */
export function PortfolioVsBenchmark({
  syncKey,
  defaultRange = "3M",
  height = 260,
  rangeOverride,
  className,
}: PortfolioVsBenchmarkProps) {
  const t = useChartTheme();
  const [picked, setPicked] = useState(() => storedRange(defaultRange));
  const range = rangeOverride ?? picked;
  const intraday = range === "1D";
  const nav = useNavDaily();
  const bench = useBenchmark("SPY", BENCH_RANGE[range]);
  const curve = useEquityCurve();
  const [read, setRead] = useState<CrosshairReadout | null>(null);
  const [ddRead, setDdRead] = useState<number | null>(null);

  const pick = (r: RangeKey) => {
    setPicked(r);
    try {
      localStorage.setItem(STORAGE_KEY, r);
    } catch {
      // storage blocked: the choice just lasts for this session
    }
  };

  // Both lines re-index at the first date they share inside the range. Without an
  // overlapping SPY history the portfolio plots alone (indexed on its own first day).
  const daily = useMemo(() => {
    const all = nav.data?.points ?? [];
    const start = range === "1D" ? null : rangeStart(range, new Date());
    const inRange = all.filter((p) => !start || p.date >= start).map((p) => ({ date: p.date, value: p.nav }));
    const spy = (bench.data?.points ?? []).map((p) => ({ date: p.date, value: p.close }));
    const aligned = alignByDate(inRange, spy);
    const withSpy = aligned.length >= 2;
    const base = withSpy ? aligned.map((a) => ({ date: a.date, value: a.a })) : inRange;
    const dd = drawdown(base.map((p) => p.value));
    return {
      total: all.length,
      inRange: inRange.length,
      withSpy,
      port: toTS(indexTo100(base)),
      spy: withSpy ? toTS(indexTo100(aligned.map((a) => ({ date: a.date, value: a.b })))) : [],
      // Same dates as the main chart, so the logical-range sync lines up bar for bar.
      dd: base.map((p, i) => ({ time: p.date, value: dd[i] })),
    };
  }, [nav.data, bench.data, range]);

  // ponytail: "1D" = the 24 h before the latest snapshot, capped by the hook's 800-row limit (~13 h).
  const intra = useMemo<TSPoint[]>(() => {
    const pts = (curve.data?.points ?? [])
      .map((p) => ({ time: unix(p.created_at), value: p.total_value }))
      .filter((p) => Number.isFinite(p.time));
    const last = pts.length ? pts[pts.length - 1].time : 0;
    return pts.filter((p) => p.time >= last - 86_400);
  }, [curve.data]);

  const main = useMemo<TSSeries[]>(
    () =>
      intraday
        ? [{ id: "nav", label: "NAV", kind: "area", data: intra, color: t.accent, fillColor: t.accentFill, format: money }]
        : [
            { id: "port", label: "Portfolio", kind: "line", data: daily.port, color: t.accent, lineWidth: 2, format: idx },
            ...(daily.withSpy
              ? [
                  {
                    id: "spy",
                    label: "SPY",
                    kind: "line" as const,
                    data: daily.spy,
                    color: t.neutral,
                    lineWidth: 2 as const,
                    format: idx,
                  },
                ]
              : []),
          ],
    [intraday, intra, daily, t],
  );

  const ddSeries = useMemo<TSSeries[]>(
    () => [
      {
        id: "dd",
        label: "Drawdown",
        kind: "area",
        data: daily.dd,
        color: t.down,
        fillColor: t.downFill,
        format: ddPct,
        scaleMargins: { top: 0.15, bottom: 0.1 },
      },
    ],
    [daily.dd, t],
  );

  // Memoized: crosshair moves re-render this component and the intraday table is ~800 rows.
  const table = useMemo(
    () =>
      intraday
        ? {
            columns: ["Time", "NAV"],
            rows: [...intra].reverse().map((p) => [unixLabel(p.time as number), money(p.value)]),
          }
        : {
            columns: ["Date", "Portfolio idx", "SPY idx", "Drawdown"],
            rows: daily.port
              .map((p, i) => [p.time as string, idx(p.value), idxOrDash(daily.spy[i]?.value), ddPct(daily.dd[i].value)])
              .reverse(),
          },
    [intraday, intra, daily],
  );

  const src = intraday ? curve : nav;
  const error = src.error
    ? failure(intraday ? "/api/desktop/equity-curve" : "/api/desktop/viz/nav-daily", src.error)
    : null;

  let empty: { message: string; hint?: string } | null = null;
  if (intraday) {
    if (intra.length < 2) {
      empty = {
        message: "No intraday snapshots yet",
        hint: "Snapshots are written every minute while the engine runs.",
      };
    }
  } else if (daily.total < MIN_DAYS) {
    empty = {
      message: "Building history",
      hint: `${daily.total} of ${MIN_DAYS} trading days recorded — the chart appears at ${MIN_DAYS}. Fewer points just plot noise. Snapshots are written every minute while the engine runs.`,
    };
  } else if (daily.port.length < MIN_DAYS) {
    empty = {
      message: "Not enough history in this range",
      hint: `${daily.inRange} of ${daily.total} recorded trading days fall inside ${range} — pick a longer range.`,
    };
  }

  const note = intraday
    ? "Benchmark is daily-only"
    : daily.withSpy
      ? null
      : bench.error
        ? `SPY history unavailable — ${failure("/api/desktop/symbol/SPY/history", bench.error)}`
        : `SPY history unavailable for these dates${
            bench.data?.source ? ` (${bench.data.source} has no closes on the portfolio's days)` : ""
          }`;

  const subtitle = intraday
    ? `Intraday NAV${intra.length ? ` since ${unixLabel(intra[0].time as number)}` : ""}`
    : `Indexed to 100 at the start of the range${
        daily.total > 0 && daily.total <= 30 ? ` · ${plural(daily.total, "trading day")} recorded` : ""
      }`;

  const legend: LegendItem[] | undefined =
    !intraday && daily.withSpy
      ? [
          { label: "Portfolio", color: t.accent, value: idxOrDash(read?.values.port) },
          { label: "SPY", color: t.neutral, value: idxOrDash(read?.values.spy) },
        ]
      : undefined;

  return (
    <ChartCard
      className={className}
      title="Portfolio vs SPY"
      subtitle={subtitle}
      legend={legend}
      toolbar={
        rangeOverride == null ? (
          <Segmented options={RANGE_OPTIONS} value={range} onChange={pick} ariaLabel="Chart range" />
        ) : undefined
      }
      table={table}
      isLoading={src.isLoading || (!intraday && bench.isLoading)}
      isFetching={src.isFetching && !src.isLoading}
      error={error}
      empty={empty}
      height={intraday ? height : height + DD_HEIGHT + 24}
    >
      {note && <p className="mb-2 text-xs text-ink-3">{note}</p>}
      {/* Keyed by range: a fresh chart fits the new window, and intraday (unix) and
          daily (business-day) time scales never share an instance. */}
      <TimeSeries
        key={range}
        series={main}
        height={height}
        syncKey={intraday ? undefined : syncKey}
        timeVisible={intraday}
        onCrosshair={setRead}
      />
      {!intraday && (
        <>
          <div className="mb-1 mt-2 flex items-baseline gap-2 text-2xs">
            <span className="font-medium uppercase tracking-wide text-ink-3">Drawdown</span>
            <span className="nums text-ink">{ddRead === null ? "—" : ddPct(ddRead)}</span>
          </div>
          <TimeSeries
            key={range}
            series={ddSeries}
            height={DD_HEIGHT}
            syncKey={syncKey}
            onCrosshair={(r) => setDdRead(r.values.dd ?? null)}
          />
        </>
      )}
    </ChartCard>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 3540BC28B48B - verify with scripts/authorship.py verify
