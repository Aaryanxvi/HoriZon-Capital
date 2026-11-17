// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-D70410A489AC
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
// Run: node --experimental-strip-types src/lib/series.check.ts   (npm run check:series)
// Hand-computed fixtures; throws on the first mismatch.
import {
  alignByDate,
  dailyFromSnapshots,
  drawdown,
  histogramBins,
  indexTo100,
  maxDrawdown,
  monthlyReturns,
  rangeStart,
  returns,
  rollingSharpe,
  rollingVol,
} from "./series.ts";

let passed = 0;

function near(actual: number, expected: number, label: string, eps = 1e-9): void {
  if (!(Math.abs(actual - expected) <= eps)) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
  passed++;
}

function same(actual: unknown, expected: unknown, label: string): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${label}: expected ${e}, got ${a}`);
  passed++;
}

// dailyFromSnapshots: last row per UTC day, input order irrelevant, bare stamps are UTC.
same(
  dailyFromSnapshots([
    { created_at: "2026-08-31 09:00:00+00:00", total_value: 110 },
    { created_at: "2026-08-30 17:11:38.363417+00:00", total_value: 101 },
    { created_at: "2026-08-30 09:00:00", total_value: 100 },
    { created_at: "2026-08-31 01:30:00+05:30", total_value: 99 }, // = Aug 30 20:00 UTC
  ]),
  [
    { date: "2026-08-30", value: 99 },
    { date: "2026-08-31", value: 110 },
  ],
  "dailyFromSnapshots",
);

// indexTo100
same(
  indexTo100([
    { date: "a", value: 50 },
    { date: "b", value: 55 },
    { date: "c", value: 45 },
  ]).map((p) => Math.round(p.value * 1e6) / 1e6),
  [100, 110, 90],
  "indexTo100",
);
same(indexTo100([{ date: "a", value: 0 }]), [], "indexTo100 zero base");

// drawdown: peak 120 then 90 → −25%
const dd = drawdown([100, 120, 90, 120, 130]);
same(dd.map((v) => Math.round(v * 1e6) / 1e6), [0, 0, -0.25, 0, 0], "drawdown");
near(maxDrawdown([100, 120, 90, 120, 130]), -0.25, "maxDrawdown");
near(maxDrawdown([1, 2, 3]), 0, "maxDrawdown monotonic");

// returns
const r = returns([100, 110, 99]);
near(r[0], 0.1, "returns[0]");
near(r[1], -0.1, "returns[1]");

// monthlyReturns: Jul measured from its own first value, Aug from Jul's last close.
// Jul 100 → 110 = +10%; Aug 110 → 121 = +10% (partial: "now" is in Aug).
const months = monthlyReturns(
  [
    { date: "2026-07-01", value: 100 },
    { date: "2026-07-31", value: 110 },
    { date: "2026-08-03", value: 115 },
    { date: "2026-08-20", value: 121 },
  ],
  new Date("2026-08-21T12:00:00Z"),
);
same(
  months.map((m) => [m.year, m.month, Math.round(m.value * 1e9) / 1e9, m.partial]),
  [
    [2026, 7, 0.1, false],
    [2026, 8, 0.1, true],
  ],
  "monthlyReturns",
);

// rollingSharpe on [0.01, 0.03, 0.02, 0.04], n = 3, annualize = 1 (so the raw ratio shows):
// w1 = [.01,.03,.02]: mean .02, sample sd .01   → 2
// w2 = [.03,.02,.04]: mean .03, sample sd .01   → 3
const sh = rollingSharpe([0.01, 0.03, 0.02, 0.04], 3, 0, 1);
same(sh.length, 2, "rollingSharpe length");
near(sh[0], 2, "rollingSharpe[0]", 1e-9);
near(sh[1], 3, "rollingSharpe[1]", 1e-9);
// rf is annual: 0.01 * 252 per year → 0.01 per period → (0.02 − 0.01)/0.01 = 1, ×√252
near(rollingSharpe([0.01, 0.03, 0.02], 3, 0.01 * 252)[0], Math.sqrt(252), "rollingSharpe rf", 1e-9);
same(Number.isNaN(rollingSharpe([0.01, 0.01, 0.01], 3)[0]), true, "rollingSharpe flat → NaN");
near(rollingVol([0.01, 0.03, 0.02], 3, 1)[0], 0.01, "rollingVol");

// histogramBins: range widened to include 0 → [0, 4], 4 bins of width 1; max lands in last bin.
same(
  histogramBins([1, 1.5, 2, 4], 4).map((b) => [b.x0, b.x1, b.count]),
  [
    [0, 1, 0],
    [1, 2, 2],
    [2, 3, 1],
    [3, 4, 1],
  ],
  "histogramBins",
);
same(histogramBins([-2, 2], 2).map((b) => b.count), [1, 1], "histogramBins symmetric");
same(histogramBins([0, 0, 0], 3).map((b) => b.count), [0, 3, 0], "histogramBins all zero");
same(histogramBins([], 5), [], "histogramBins empty");

// alignByDate: inner join, a's order
same(
  alignByDate(
    [
      { date: "d1", value: 1 },
      { date: "d2", value: 2 },
      { date: "d3", value: 3 },
    ],
    [
      { date: "d3", value: 30 },
      { date: "d1", value: 10 },
    ],
  ),
  [
    { date: "d1", a: 1, b: 10 },
    { date: "d3", a: 3, b: 30 },
  ],
  "alignByDate",
);

// rangeStart
const now = new Date("2026-03-31T15:00:00Z");
same(rangeStart("1W", now), "2026-03-24", "rangeStart 1W");
same(rangeStart("1M", now), "2026-02-28", "rangeStart 1M clamps day");
same(rangeStart("3M", now), "2025-12-31", "rangeStart 3M crosses year");
same(rangeStart("YTD", now), "2026-01-01", "rangeStart YTD");
same(rangeStart("1Y", now), "2025-03-31", "rangeStart 1Y");
same(rangeStart("ALL", now), null, "rangeStart ALL");

console.log(`series.check: ${passed} checks passed`);
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token D70410A489AC - verify with scripts/authorship.py verify
