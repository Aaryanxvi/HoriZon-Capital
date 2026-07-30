"""Industry-peer benchmarks for the paper's performance tables.

"Beats SPY" is a weak claim for a hedge-fund system: SPY is a long-only equity
index, not a peer. This script adds peer benchmarks computed on the SAME
calendars, the SAME metric definitions and the SAME risk-free rate as every
other table, so the rows are directly comparable:

  SPY   S&P 500 buy-and-hold          -- the existing equity benchmark (control:
                                         must reproduce the published numbers)
  QAI   IQ Hedge Multi-Strategy       -- investable replication of the aggregate
        Tracker ETF                      hedge-fund industry return stream. The
                                         closest free stand-in for HFRI-type
                                         "industry average" indices, which are
                                         licensed.
  AOR   iShares Core Growth Allocation-- classic 60/40 balanced portfolio, the
                                         default "what else would you do with
                                         the money" comparison.

HONEST CAVEATS, to be carried into the paper rather than buried:
  * QAI inception 2009-03, AOR inception 2008-11. Neither spans the whole
    2008-2017 holdout; the script reports each benchmark's actual first date and
    the coverage it achieved, and a partial-window benchmark that MISSES the
    2008 crash is flattered, not penalised, by the gap. Read those rows as a
    lower bound on our relative drawdown advantage.
  * Both are ETFs, so their returns are net of their own expense ratios, while
    HFRI-style indices are net of manager fees but carry well-documented
    survivorship and backfill bias. A replication ETF understates neither.
  * These are benchmarks, not strategy arms. Nothing here changes any config.

Usage:
    python scripts/validate_benchmarks.py
    python scripts/validate_benchmarks.py --start 2008-01-01 --end 2017-12-31
    python scripts/validate_benchmarks.py --selfcheck
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from scripts.validate_sleeve_attribution import metrics  # noqa: E402

# (symbol, label as it should appear in the paper)
BENCHMARKS = [
    ("SPY.US", "SPY buy-and-hold"),
    ("QAI.US", "Hedge-fund industry (QAI)"),
    ("AOR.US", "60/40 balanced (AOR)"),
]

# The two evaluation windows the paper already uses.
WINDOWS = {
    "selection": ("2018-01-01", "2024-12-31"),
    "holdout": ("2008-01-01", "2017-12-31"),
}


def bench_row(closes: pd.Series, label: str, start: str, end: str,
              capital: float) -> dict | None:
    """Metrics for one benchmark over one window, plus its real coverage.

    Returns None when the instrument did not exist in the window at all.
    """
    px = closes.loc[pd.Timestamp(start):pd.Timestamp(end)].dropna()
    if len(px) < 30:
        return None
    eq = (px / px.iloc[0]) * capital
    row = metrics(eq, label)
    row["first"] = str(px.index[0].date())
    row["last"] = str(px.index[-1].date())
    # Fraction of the requested window the instrument actually covers.
    want = pd.Timestamp(end) - pd.Timestamp(start)
    got = px.index[-1] - px.index[0]
    row["coverage%"] = round(got / want * 100, 1) if want.days else 100.0
    return row


async def amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default=None, help="override; default = both paper windows")
    p.add_argument("--end", default=None)
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    if args.start and args.end:
        windows = {"custom": (args.start, args.end)}
    else:
        windows = WINDOWS

    symbols = [s for s, _ in BENCHMARKS]
    print(f"Fetching {len(symbols)} benchmark series, 20y daily...")
    bars = await fetch_batch(symbols, period="20y")
    missing = [s for s in symbols if s not in bars]
    if missing:
        print(f"[WARN] no data for {missing} -- those rows are omitted, not zero-filled.")

    for wname, (start, end) in windows.items():
        print(f"\n=== {wname}: {start} .. {end} ===")
        print(f"{'benchmark':28s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} "
              f"{'maxDD%':>7s} {'cover%':>7s}  window")
        for sym, label in BENCHMARKS:
            df = bars.get(sym)
            if df is None:
                continue
            row = bench_row(df["close"], label, start, end, args.capital)
            if row is None:
                print(f"{label:28s} {'--':>7s} {'--':>6s} {'--':>7s} {'--':>7s} "
                      f"{'0':>7s}  did not exist in this window")
                continue
            print(f"{row['label']:28s} {row['CAGR%']:>7} {row['vol%']:>6} "
                  f"{row['Sharpe']:>7} {row['maxDD%']:>7} {row['coverage%']:>7}  "
                  f"{row['first']}..{row['last']}")

    print("\nCaveat for the paper: QAI (2009-03) and AOR (2008-11) post-date the "
          "start of the\n2008-2017 holdout, so on that window they SKIP part or "
          "all of the crash. A\npartial benchmark is flattered by the gap -- treat "
          "our relative drawdown edge\nthere as a lower bound, and report each "
          "benchmark's coverage alongside it.")


def _selfcheck() -> None:
    """Runnable check of the window/coverage logic -- no data, no network."""
    idx = pd.date_range("2018-01-01", "2024-12-31", freq="B")
    # Flat series: zero return, zero vol, Sharpe floor, no drawdown.
    flat = pd.Series(100.0, index=idx)
    row = bench_row(flat, "flat", "2018-01-01", "2024-12-31", 100_000.0)
    assert row is not None and row["CAGR%"] == 0.0 and row["maxDD%"] == 0.0, row
    assert row["coverage%"] > 99.0, row

    # A late-inception benchmark must report its real first date and partial
    # coverage, never silently pretend to span the whole window.
    late = pd.Series(100.0, index=pd.date_range("2022-01-03", "2024-12-31", freq="B"))
    row = bench_row(late, "late", "2018-01-01", "2024-12-31", 100_000.0)
    assert row is not None and row["first"] == "2022-01-03", row
    assert row["coverage%"] < 50.0, row

    # An instrument absent from the window is dropped, not zero-filled.
    assert bench_row(late, "late", "2008-01-01", "2017-12-31", 100_000.0) is None

    # Doubling over ~1 year is ~100% CAGR, and the metric wiring is live.
    yr = pd.date_range("2020-01-01", periods=252, freq="B")
    up = pd.Series([100.0 * (2 ** (i / 251)) for i in range(252)], index=yr)
    row = bench_row(up, "up", "2020-01-01", "2021-12-31", 100_000.0)
    assert row is not None and 95.0 < row["CAGR%"] < 105.0, row
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        asyncio.run(amain())
