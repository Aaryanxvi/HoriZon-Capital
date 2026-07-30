"""2008-17 holdout SHIP GATE: current live mix vs no-breadth candidate.

Pre-registered before running. The 2008-17 window is UNTOUCHED by the sleeve
selection that produced the no-breadth candidate (attribution ran on 2018-24) —
that's the point: an out-of-sample check on whether dropping breadth generalizes.

ARMS (identical harness/params/fill model as validate_sleeve_attribution.py):
  a) CURRENT   breadth .40 / research .30 / trend .20 / momrank .10
  b) CANDIDATE research .500 / trend .333 / momrank .167  (LOO-breadth renorm)
  c) SPY       buy-hold, same window

GATES (both must pass to recommend the reweight; recommendation only — the
actual config change happens on main separately, never here):
  G1: candidate Sharpe  >  current Sharpe
  G2: candidate maxDD   no more than 5pts worse than current maxDD

CACHE TRAP (why this is a separate script, not a param on the 2018-24 run):
fetch_batch caches per-symbol IGNORING period, WITHIN a process. Each `python
scripts/...` run is a fresh process with an empty in-memory cache (the price
cache is module-level in batch_bars.py, not on disk — only PIT *membership* is
disk-cached in ~/.horizon-capital, which we leave alone). So a fresh process
can't be poisoned by the 2018-24 run's 10y frames. The real trap is PERIOD: from
2026, period="10y" only reaches ~2016 and would silently give empty 2008-17
windows. This script fetches period="max" and then HARD-ASSERTS that a sample of
symbols actually carry 2008 dates before any arm runs — abort otherwise.

Usage:
    python scripts/validate_holdout_gate.py --start 2008-01-01 --end 2017-12-31
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
from app.data_layer.pit_universe import union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS, get_universe  # noqa: E402
from scripts.validate_sleeve_attribution import (  # noqa: E402
    LIVE_CFG,
    LIVE_WEIGHTS,
    _base,
    _loo_weights,
    metrics,
    run,
)

# Candidate = the exact LOO-breadth renormalization. Assert it matches so a stray
# edit to LIVE_WEIGHTS can't silently change what we gate.
CANDIDATE_WEIGHTS = _loo_weights("breadth_alpha")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2008-01-01")
    p.add_argument("--end", default="2017-12-31")
    p.add_argument("--capital", type=float, default=100_000.0)
    args = p.parse_args()

    assert set(CANDIDATE_WEIGHTS) == {"research_stack", "trend_filter", "momentum_rank"}
    assert abs(CANDIDATE_WEIGHTS["research_stack"] - 0.5) < 1e-9, CANDIDATE_WEIGHTS

    config_universe = get_universe("config")
    pit = union_members(args.start, args.end)
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)
    # period="max": 10y from 2026 misses 2008-17 entirely. Single fetch, before
    # any run() — same fetch-ordering discipline as the sibling scripts.
    print(f"Fetching {len(tickers)} tickers (PIT union + anchors), period=max ...")
    bars = asyncio.run(fetch_batch(tickers, period="max"))
    cov = len(bars)
    print(f"Coverage: {cov}/{len(tickers)} "
          f"({100*cov/len(tickers):.0f}%; missing = delisted, bigger GFC-era gap)")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"

    # HARD VERIFY: bars must actually reach into 2008, else the fetch/period is
    # wrong and every equity curve would be garbage. Check the anchors + SPY that
    # certainly existed in 2008.
    start_ts = pd.Timestamp(args.start)
    probe = [c for c in (spy_col, "QQQ.NASDAQ", "AAPL.NASDAQ", "TLT.NASDAQ",
                         "GLD.NYSE") if c in closes.columns]
    assert probe, "no probe symbols present at all — fetch failed"
    have_2008 = {}
    for c in probe:
        first = closes[c].dropna().index.min()
        have_2008[c] = first
    reached = [c for c, first in have_2008.items() if first <= start_ts]
    print("2008-date verification (first available close per probe symbol):")
    for c, first in have_2008.items():
        print(f"  {c:14s} first={first.date()}  "
              f"{'OK' if first <= start_ts else 'MISSING 2008'}")
    if not reached:
        print("\nABORT: no probe symbol carries data at/before "
              f"{start_ts.date()} — fetched period does not span the holdout "
              "window. Not running any arm (would produce garbage curves).")
        sys.exit(2)

    win = (closes.index >= start_ts) & (closes.index <= pd.Timestamp(args.end))
    cal = closes.index[win]
    n_days = int(win.sum())
    print(f"Holdout calendar: {cal[0].date()} -> {cal[-1].date()}  ({n_days} days)")
    assert n_days > 500, f"only {n_days} bars in window — window too thin, abort"

    def _run(weights):
        return run(LIVE_CFG, weights, bars, closes, opens, cal, args.capital,
                   config_universe)

    print("\nRunning CURRENT mix ...")
    eq_cur, g_cur = _run(LIVE_WEIGHTS)
    m_cur = metrics(eq_cur, "current", g_cur)

    print("Running CANDIDATE no-breadth mix ...")
    eq_cand, g_cand = _run(CANDIDATE_WEIGHTS)
    m_cand = metrics(eq_cand, "candidate", g_cand)

    spx = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
    m_spy = metrics((spx / spx.iloc[0]) * args.capital, "SPY")

    rows = [m_cur, m_cand, m_spy]
    print(f"\n{'variant':12s} {'CAGR%':>7s} {'vol%':>6s} {'Sharpe':>7s} "
          f"{'maxDD%':>7s} {'avgGross%':>10s}")
    for m in rows:
        print(f"{m['label']:12s} {m['CAGR%']:>7} {m['vol%']:>6} {m['Sharpe']:>7} "
              f"{m['maxDD%']:>7} {m['avgGross%']:>10}")

    # G1: Sharpe strictly better. G2: maxDD (negative) no more than 5pts worse.
    g1 = m_cand["Sharpe"] > m_cur["Sharpe"]
    g2 = m_cand["maxDD%"] >= m_cur["maxDD%"] - 5.0
    print(f"\nG1 (candidate Sharpe > current): {m_cand['Sharpe']} > "
          f"{m_cur['Sharpe']} -> {'PASS' if g1 else 'FAIL'}")
    print(f"G2 (candidate maxDD >= current - 5pts): {m_cand['maxDD%']} >= "
          f"{m_cur['maxDD%'] - 5.0:.1f} -> {'PASS' if g2 else 'FAIL'}")
    verdict = ("RECOMMEND reweight to no-breadth mix" if (g1 and g2)
               else "KEEP current mix (gate failed)")
    print(f"\nVerdict: {verdict}")
    print("\nCaveats: quality tilt stubbed (look-ahead), delisted prices missing")
    print("(bigger GFC-era gap, biases both arms equally). Recommendation only —")
    print("actual config change happens on main separately, not from this run.")


def _selfcheck() -> None:
    """No-network check of the gate logic + candidate-weight identity."""
    assert set(CANDIDATE_WEIGHTS) == {"research_stack", "trend_filter", "momentum_rank"}
    assert abs(sum(CANDIDATE_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(CANDIDATE_WEIGHTS["research_stack"] - 0.5) < 1e-9
    assert abs(CANDIDATE_WEIGHTS["trend_filter"] - 1 / 3) < 1e-9
    assert abs(CANDIDATE_WEIGHTS["momentum_rank"] - 1 / 6) < 1e-9

    # Gate booleans behave as specified.
    def gates(cur_sh, cur_dd, cand_sh, cand_dd):
        return (cand_sh > cur_sh, cand_dd >= cur_dd - 5.0)

    assert gates(0.5, -30.0, 0.6, -32.0) == (True, True)   # better Sharpe, DD within 5
    assert gates(0.5, -30.0, 0.6, -36.0) == (True, False)  # DD >5pts worse -> G2 fail
    assert gates(0.5, -30.0, 0.5, -30.0) == (False, True)  # equal Sharpe -> G1 fail
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
