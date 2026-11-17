// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-8AC65C264C14
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
// Pure series math for the charts. No imports on purpose: series.check.ts runs
// this file directly with `node --experimental-strip-types`.
// Returns, drawdowns and monthly values are FRACTIONS (0.012 = 1.2%).

export type DatedValue = { date: string; value: number };
export type MonthlyReturn = { year: number; month: number; value: number; partial: boolean };
export type Bin = { x0: number; x1: number; count: number };
export type RangeKey = "1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL";

// Snapshot timestamps look like "2026-08-30 17:11:38.363417+00:00"; bare ones are UTC.
function parseUtc(ts: string): number {
  const iso = ts.replace(" ", "T");
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

function isoDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Last snapshot per UTC calendar day, ascending. */
export function dailyFromSnapshots(
  points: { created_at: string; total_value: number }[],
): DatedValue[] {
  const rows = points
    .map((p) => ({ ms: parseUtc(p.created_at), value: p.total_value }))
    .filter((r) => Number.isFinite(r.ms) && Number.isFinite(r.value))
    .sort((a, b) => a.ms - b.ms);
  const byDay = new Map<string, number>();
  for (const r of rows) byDay.set(isoDate(r.ms), r.value);
  return [...byDay].map(([date, value]) => ({ date, value }));
}

/** Rebase so the first point is 100. Empty when the base is 0 (undefined ratio). */
export function indexTo100(points: DatedValue[]): DatedValue[] {
  const base = points[0]?.value;
  if (!base) return [];
  return points.map((p) => ({ date: p.date, value: (p.value / base) * 100 }));
}

/** Distance below the running peak, ≤ 0. */
export function drawdown(values: number[]): number[] {
  let peak = -Infinity;
  return values.map((v) => {
    peak = Math.max(peak, v);
    return peak > 0 ? v / peak - 1 : 0;
  });
}

export function maxDrawdown(values: number[]): number {
  return Math.min(0, ...drawdown(values));
}

/** Simple period returns; length n − 1. */
export function returns(values: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < values.length; i++) {
    out.push(values[i - 1] ? values[i] / values[i - 1] - 1 : 0);
  }
  return out;
}

/**
 * Month return = last value of the month / last value of the previous month − 1
 * (equivalent to compounding the daily returns). The first month is measured from
 * its own first value. `partial` marks the current UTC month.
 */
export function monthlyReturns(daily: DatedValue[], now: Date = new Date()): MonthlyReturn[] {
  const current = now.toISOString().slice(0, 7);
  const months: { key: string; first: number; last: number }[] = [];
  for (const p of daily) {
    const key = p.date.slice(0, 7);
    const m = months[months.length - 1];
    if (m && m.key === key) m.last = p.value;
    else months.push({ key, first: p.value, last: p.value });
  }
  return months.map((m, i) => {
    const base = i > 0 ? months[i - 1].last : m.first;
    return {
      year: Number(m.key.slice(0, 4)),
      month: Number(m.key.slice(5, 7)),
      value: base ? m.last / base - 1 : 0,
      partial: m.key === current,
    };
  });
}

/** fn over each trailing window of n; output[j] ends at values[j + n − 1]. */
export function rolling(values: number[], n: number, fn: (window: number[]) => number): number[] {
  const out: number[] = [];
  for (let i = n; i <= values.length; i++) out.push(fn(values.slice(i - n, i)));
  return out;
}

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function stdev(xs: number[]): number {
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

/** Annualised sample volatility of each trailing window. */
export function rollingVol(rets: number[], n: number, annualize = 252): number[] {
  return rolling(rets, n, (w) => stdev(w) * Math.sqrt(annualize));
}

/** Annualised Sharpe of each window; `rf` is an annual rate. NaN when the window is flat. */
export function rollingSharpe(rets: number[], n: number, rf = 0, annualize = 252): number[] {
  return rolling(rets, n, (w) => {
    const sd = stdev(w);
    return sd ? ((mean(w) - rf / annualize) / sd) * Math.sqrt(annualize) : NaN;
  });
}

/** n equal-width bins over [min, max], widened to include 0 (returns read against zero). */
export function histogramBins(values: number[], n: number): Bin[] {
  const xs = values.filter(Number.isFinite);
  if (!xs.length || n < 1) return [];
  let lo = Math.min(0, ...xs);
  let hi = Math.max(0, ...xs);
  // ponytail: all-zero input gets a hairline-wide window so the mass still sits in one bin.
  if (lo === hi) {
    lo = -1e-9;
    hi = 1e-9;
  }
  const width = (hi - lo) / n;
  const bins: Bin[] = Array.from({ length: n }, (_, i) => ({
    x0: lo + i * width,
    x1: i === n - 1 ? hi : lo + (i + 1) * width,
    count: 0,
  }));
  for (const x of xs) bins[Math.min(n - 1, Math.floor((x - lo) / width))].count++;
  return bins;
}

/** Inner join on date, in `a`'s order. */
export function alignByDate(
  a: DatedValue[],
  b: DatedValue[],
): { date: string; a: number; b: number }[] {
  const other = new Map(b.map((p) => [p.date, p.value]));
  const out: { date: string; a: number; b: number }[] = [];
  for (const p of a) {
    const v = other.get(p.date);
    if (v !== undefined) out.push({ date: p.date, a: p.value, b: v });
  }
  return out;
}

function minusMonths(now: Date, months: number): Date {
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth() - months;
  // Clamp the day so Mar 31 − 1M is Feb 28/29, not Mar 3.
  const lastDay = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  return new Date(Date.UTC(y, m, Math.min(now.getUTCDate(), lastDay)));
}

/** First date ("YYYY-MM-DD", UTC) inside the range; null for ALL. */
export function rangeStart(range: RangeKey, now: Date): string | null {
  switch (range) {
    case "1W":
      return isoDate(now.getTime() - 7 * 86_400_000);
    case "1M":
      return isoDate(minusMonths(now, 1).getTime());
    case "3M":
      return isoDate(minusMonths(now, 3).getTime());
    case "YTD":
      return `${now.getUTCFullYear()}-01-01`;
    case "1Y":
      return isoDate(minusMonths(now, 12).getTime());
    default:
      return null;
  }
}
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 8AC65C264C14 - verify with scripts/authorship.py verify
