// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-8140E5C3A0B4
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import clsx from "clsx";
import { useMemo, useState } from "react";

import {
  CalendarHeatmap,
  calendarTable,
  ChartCard,
  Histogram,
  StatTile,
  TimeSeries,
  type TSSeries,
} from "@/components/charts";
import { PortfolioVsBenchmark, type RangeKey } from "@/components/PortfolioVsBenchmark";
import { Card, Empty, ErrorNote, Loading, PageHeader, Segmented, Table } from "@/components/ui";
import { ApiError, usePerformance } from "@/lib/api";
import { useChartTheme } from "@/lib/colors";
import { dateTime, num } from "@/lib/format";
import {
  histogramBins,
  monthlyReturns,
  returns,
  rollingSharpe,
  rollingVol,
  type DatedValue,
} from "@/lib/series";
import { useBenchmark, useNavDaily, type BenchmarkPoint } from "@/lib/viz-api";

const PERIODS = ["1d", "7d", "30d", "90d", "YTD", "ALL"] as const;
type Period = (typeof PERIODS)[number];
const PERIOD_OPTIONS = PERIODS.map((p) => ({ value: p, label: p }));
const RANGE_FOR: Record<Period, RangeKey> = { "1d": "1D", "7d": "1W", "30d": "1M", "90d": "3M", YTD: "YTD", ALL: "ALL" };
const DAYS_FOR: Record<Exclude<Period, "YTD" | "ALL">, number> = { "1d": 1, "7d": 7, "30d": 30, "90d": 90 };
const PERIOD_KEY = "horizon-perf-period";
const WINDOW = 20;

function storedPeriod(): Period {
  try {
    const v = localStorage.getItem(PERIOD_KEY);
    return (PERIODS as readonly string[]).includes(v ?? "") ? (v as Period) : "30d";
  } catch {
    return "30d";
  }
}

type MetricRow = Record<string, number | string>;

/** A metric only when the snapshot actually holds a number — never a fabricated 0. */
function metric(row: MetricRow | undefined, key: string): number | null {
  const v = row?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const show = (v: number | null, format: (v: number) => string) => (v === null ? "—" : format(v));
/** Signed percent from a FRACTION: 0.0123 → "+1.23%", −0.004 → "−0.40%". */
const sPct = (v: number, d = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
/** Ratios explode when drawdown/downside ≈ 0 (Sortino 147,420,416): ≥10k → "147.4M", ≥1k → no decimals. */
const ratio = (v: number) => (Math.abs(v) >= 10_000 ? compact.format(v) : num(v, Math.abs(v) >= 1_000 ? 0 : 2));
/** Full value as a tooltip wherever `ratio` dropped digits. */
const ratioTitle = (v: number) => (Math.abs(v) >= 1_000 ? num(v, 2) : undefined);
const volPct = (v: number) => `${(v * 100).toFixed(1)}%`;

// performance.* returns and max_drawdown are FRACTIONS.
// Annualised figures and ratios from a few days (+48% "annualised" off 3 days) or a
// handful of trades are noise that reads as a result, so they stay hidden until then.
const MIN_DAYS = 30;
const MIN_TRADES = 10;

type Metric = {
  key: string;
  label: string;
  format: (v: number) => string;
  title?: (v: number) => string | undefined;
  needs?: "days" | "trades";
};

const METRICS: Metric[] = [
  { key: "total_return", label: "Total return", format: sPct },
  { key: "annualized_return", label: "Annualised", format: sPct, needs: "days" },
  { key: "sharpe_ratio", label: "Sharpe", format: ratio, title: ratioTitle, needs: "days" },
  { key: "max_drawdown", label: "Max drawdown", format: (v) => `${v ? "−" : ""}${Math.abs(v * 100).toFixed(2)}%` },
  { key: "sortino_ratio", label: "Sortino", format: ratio, title: ratioTitle, needs: "days" },
  { key: "calmar_ratio", label: "Calmar", format: ratio, title: ratioTitle, needs: "days" },
  { key: "win_rate", label: "Win rate", format: (v) => `${(v * 100).toFixed(1)}%`, needs: "trades" },
  { key: "profit_factor", label: "Profit factor", format: ratio, title: ratioTitle, needs: "trades" },
];

/** Why a metric is withheld ("3 of 30 days needed"), or null when it has enough data. */
function notYet(m: Metric, days: number, trades: number | null): string | null {
  if (m.needs === "days" && days < MIN_DAYS) return `${days} of ${MIN_DAYS} days needed`;
  if (m.needs === "trades" && (trades ?? 0) < MIN_TRADES) return `${trades ?? 0} of ${MIN_TRADES} trades needed`;
  return null;
}

function failure(endpoint: string, e: unknown): string {
  const why = e instanceof ApiError ? `HTTP ${e.status}` : e instanceof Error ? e.message : "request failed";
  return `GET ${endpoint} failed (${why})`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** First date of the period's window; ALL starts at the portfolio's first recorded day. */
function windowStart(period: Period, now: Date, inception: string | undefined): string | null {
  if (period === "YTD") return `${now.getUTCFullYear()}-01-01`;
  if (period === "ALL") return inception ?? null;
  return new Date(now.getTime() - DAYS_FOR[period] * 86_400_000).toISOString().slice(0, 10);
}

/** SPY price return from the last close on/before `start` to the latest close; null if not covered. */
function spyReturn(closes: BenchmarkPoint[], start: string | null) {
  if (!start) return null;
  let base = -1;
  for (let i = 0; i < closes.length && closes[i].date <= start; i++) base = i;
  const last = closes.length - 1;
  if (base < 0 || base === last || !closes[base].close) return null;
  return { value: closes[last].close / closes[base].close - 1, from: closes[base].date, to: closes[last].date };
}

/** Formatted metric with the full value as its tooltip when the format dropped digits. */
function Titled({ v, m, blocked }: { v: number | null; m: Metric; blocked?: string | null }) {
  if (blocked) return <span title={blocked}>—</span>;
  return <span title={v === null ? undefined : m.title?.(v)}>{show(v, m.format)}</span>;
}

function KpiGrid({
  row,
  days,
  loading,
  error,
}: {
  row: MetricRow | undefined;
  days: number;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <Loading label="Loading performance" />;
  if (error) return <ErrorNote message={error} />;
  if (!row)
    return (
      <Card bodyClassName="">
        <Empty
          message="No performance snapshot for this period yet"
          hint="The performance worker writes every window about 15 minutes after the engine starts, then every 15 minutes."
        />
      </Card>
    );
  const trades = metric(row, "total_trades");
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
      {METRICS.map((m) => {
        const blocked = notYet(m, days, trades);
        return (
          <StatTile
            key={m.key}
            label={m.label}
            value={<Titled v={metric(row, m.key)} m={m} blocked={blocked} />}
            hint={
              blocked ??
              (m.key === "total_return" && row.created_at
                ? `as of ${dateTime(String(row.created_at))}`
                : m.key === "win_rate" && trades !== null
                  ? plural(trades, "trade")
                  : undefined)
            }
          />
        );
      })}
    </div>
  );
}

export default function PerformancePage() {
  const t = useChartTheme();
  const [period, setPeriod] = useState<Period>(storedPeriod);
  const perf = usePerformance();
  const nav = useNavDaily();
  // SPY column covers every period row (up to ALL), so fetch the widest window once.
  const bench = useBenchmark("SPY", "5Y");

  const pickPeriod = (p: Period) => {
    setPeriod(p);
    try {
      localStorage.setItem(PERIOD_KEY, p);
    } catch {
      // storage blocked: the choice just lasts for this session
    }
  };

  const daily = useMemo<DatedValue[]>(
    () => (nav.data?.points ?? []).map((p) => ({ date: p.date, value: p.nav })),
    [nav.data],
  );
  const rets = useMemo(() => returns(daily.map((d) => d.value)), [daily]);
  const navError = nav.error ? failure("/api/desktop/viz/nav-daily", nav.error) : null;
  const daysRecorded = `${plural(daily.length, "trading day")} recorded`;

  // Monthly returns, compounded into year totals.
  const cells = useMemo(() => monthlyReturns(daily), [daily]);
  const yearTotals = useMemo(() => {
    const out: Record<number, number> = {};
    for (const c of cells) out[c.year] = (1 + (out[c.year] ?? 0)) * (1 + c.value) - 1;
    return out;
  }, [cells]);

  // Rolling window j ends on return j + WINDOW − 1, i.e. on daily[j + WINDOW].
  const rolling = useMemo(() => {
    if (rets.length < WINDOW + 1) return null;
    const at = (i: number) => daily[i + WINDOW].date;
    return {
      vol: rollingVol(rets, WINDOW).map((value, i) => ({ time: at(i), value })),
      sharpe: rollingSharpe(rets, WINDOW).map((value, i) => ({ time: at(i), value })),
    };
  }, [daily, rets]);
  const volSeries = useMemo<TSSeries[]>(
    () => [
      { id: "vol", label: "Volatility (annualised)", kind: "line", data: rolling?.vol ?? [], color: t.series[0], format: volPct },
    ],
    [rolling, t],
  );
  const sharpeSeries = useMemo<TSSeries[]>(
    () => [{ id: "sharpe", label: "Sharpe", kind: "line", data: rolling?.sharpe ?? [], color: t.series[0], format: ratio }],
    [rolling, t],
  );

  const meanRet = rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : 0;
  const bins = useMemo(() => histogramBins(rets, 15), [rets]);

  const periods = perf.data?.periods ?? {};
  const listed = PERIODS.filter((p) => periods[p]);
  const now = new Date();
  const closes = bench.data?.points ?? [];

  return (
    <>
      <PageHeader title="Performance" subtitle="Written by the performance worker every 15 minutes" />

      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-3">Period</span>
          <Segmented options={PERIOD_OPTIONS} value={period} onChange={pickPeriod} size="md" ariaLabel="Performance period" />
        </div>

        <KpiGrid
          row={periods[period]}
          days={daily.length}
          loading={perf.isLoading}
          error={perf.error ? failure("/api/desktop/performance", perf.error) : null}
        />

        <div className="grid gap-3 lg:grid-cols-2">
          <PortfolioVsBenchmark className="lg:col-span-2" syncKey="perf-pvb" rangeOverride={RANGE_FOR[period]} />

          <ChartCard
            className="lg:col-span-2"
            title="Monthly returns"
            subtitle={daysRecorded}
            table={calendarTable(cells, sPct, yearTotals)}
            isLoading={nav.isLoading}
            isFetching={nav.isFetching && !nav.isLoading}
            error={navError}
            empty={
              daily.length < 2
                ? {
                    message: "Not enough daily history yet",
                    hint: `${daysRecorded} — monthly returns appear once two have closed. Snapshots are written every minute while the engine runs.`,
                  }
                : null
            }
          >
            <CalendarHeatmap cells={cells} format={sPct} yearTotals={yearTotals} />
          </ChartCard>

          <ChartCard
            title="Rolling 20-day metrics"
            subtitle={rolling ? `${plural(rolling.vol.length, "window")} · ${daysRecorded}` : daysRecorded}
            table={
              rolling
                ? {
                    columns: ["Date", "Volatility (ann.)", "Sharpe"],
                    rows: rolling.vol
                      .map((p, i) => [p.time, volPct(p.value), show(Number.isFinite(rolling.sharpe[i].value) ? rolling.sharpe[i].value : null, ratio)])
                      .reverse(),
                  }
                : undefined
            }
            isLoading={nav.isLoading}
            isFetching={nav.isFetching && !nav.isLoading}
            error={navError}
            empty={
              rolling
                ? null
                : {
                    message: "Not enough history for a 20-day window",
                    hint: `Needs 21 trading days; ${rets.length} recorded so far`,
                  }
            }
          >
            <div className="mb-1 text-2xs font-medium uppercase tracking-wide text-ink-3">
              Rolling 20-day volatility (annualised)
            </div>
            <TimeSeries series={volSeries} height={110} syncKey="perf-rolling" />
            <div className="mb-1 mt-3 text-2xs font-medium uppercase tracking-wide text-ink-3">Rolling 20-day Sharpe</div>
            <TimeSeries series={sharpeSeries} height={110} syncKey="perf-rolling" />
          </ChartCard>

          <ChartCard
            title="Daily return distribution"
            subtitle={`${plural(rets.length, "daily return")} · mean ${sPct(meanRet)}`}
            table={{
              columns: ["From", "To", "Days", "Share"],
              rows: bins.map((b) => [
                sPct(b.x0),
                sPct(b.x1),
                b.count,
                `${rets.length ? Math.round((b.count / rets.length) * 100) : 0}%`,
              ]),
            }}
            isLoading={nav.isLoading}
            isFetching={nav.isFetching && !nav.isLoading}
            error={navError}
            empty={
              rets.length < 5
                ? { message: "Not enough daily returns yet", hint: `Needs 5 daily returns; ${rets.length} recorded so far` }
                : null
            }
          >
            <Histogram values={rets} format={sPct} refs={[{ value: meanRet, label: "mean" }]} />
          </ChartCard>
        </div>

        <Card title="Metrics by period" subtitle="Highlighted row = selected period" bodyClassName="">
          {perf.isLoading ? (
            <Loading />
          ) : listed.length === 0 ? (
            <Empty
              message="No performance snapshots yet"
              hint="The first window lands about 15 minutes after the engine starts."
            />
          ) : (
            <Table
              head={[
                "Period",
                ...METRICS.map((m) => m.label),
                "Alpha IN",
                "Alpha US",
                <span key="spy">
                  SPY total return
                  <span className="block font-normal normal-case">(price return, computed)</span>
                </span>,
              ]}
            >
              {listed.map((p) => {
                const row = periods[p];
                const spy = spyReturn(closes, windowStart(p, now, daily[0]?.date));
                return (
                  <tr key={p} className={clsx("row-hover", p === period && "bg-surface-2")}>
                    <td className="td font-medium">{p}</td>
                    {METRICS.map((m) => (
                      <td key={m.key} className="td nums text-right">
                        <Titled
                          v={metric(row, m.key)}
                          m={m}
                          blocked={notYet(m, daily.length, metric(row, "total_trades"))}
                        />
                      </td>
                    ))}
                    <td className="td nums text-right">{show(metric(row, "alpha_india"), (v) => num(v, 3))}</td>
                    <td className="td nums text-right">{show(metric(row, "alpha_us"), (v) => num(v, 3))}</td>
                    <td
                      className="td nums text-right"
                      title={spy ? `SPY close ${spy.from} → ${spy.to}` : "No SPY closes cover this window"}
                    >
                      {spy ? sPct(spy.value) : "—"}
                    </td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 8140E5C3A0B4 - verify with scripts/authorship.py verify
