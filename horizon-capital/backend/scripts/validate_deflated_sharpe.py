# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-66E43B19BEEA
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Deflated and probabilistic Sharpe ratios for the production mix.

The paper cites Bailey and Lopez de Prado on backtest overfitting but reports
only raw Sharpe ratios. That is exactly the gap their result is about: a Sharpe
ratio selected as the best of many trials is biased upward, and the size of the
bias grows with the number of trials. Since our own methodology section admits
to evaluating multiple sleeve mixes, the raw figure needs deflating before it
can be read as evidence.

Reports, for both paper windows:

  SR    the raw annualised Sharpe ratio already in Tables I and IV
  PSR   probability the TRUE Sharpe exceeds a benchmark, correcting for the
        skew and excess kurtosis of the return distribution (a high raw SR
        earned through negatively-skewed returns is worth less)
  DSR   probability the true Sharpe exceeds zero AFTER deflating for having
        selected the best of N trials

N is not knowable exactly, so rather than pick a flattering value we report a
sensitivity across a range that brackets what this project actually ran, and
let the reader choose. Trials counted generously means a LOWER reported DSR;
we prefer that direction.

Usage:
    python scripts/validate_deflated_sharpe.py
    python scripts/validate_deflated_sharpe.py --selfcheck
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRADING_DAYS = 252

from app.data_layer.batch_bars import fetch_batch  # noqa: E402
from app.data_layer.pit_universe import union_members  # noqa: E402
from app.data_layer.universe import _ANCHORS, get_universe  # noqa: E402
from app.quant.metrics_advanced import (  # noqa: E402
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from scripts.validate_sleeve_attribution import (  # noqa: E402
    LIVE_CFG,
    _base,
    _loo_weights,
    metrics,
    run,
)

PROD_WEIGHTS = _loo_weights("breadth_alpha")
PAPER_DIR = ROOT.parent / "own research paper"

WINDOWS = {
    "selection 2018-2024": ("2018-01-01", "2024-12-31"),
    "holdout 2008-2017": ("2008-01-01", "2017-12-31"),
}

# Trial counts to report. The middle value is our honest estimate of what this
# project evaluated (sleeve mixes, momentum top-N variants, breadth weightings,
# volatility targets, the overlay); the outer values bracket it so a reader who
# thinks we searched harder can read across.
TRIAL_COUNTS = (5, 20, 50)

# Sharpe ratios actually observed across the variants this project evaluated,
# taken from the attribution and gate runs archived alongside the paper
# (full mix, four standalone sleeves, four leave-one-out mixes, the momentum
# top-10 variant, and the holdout incumbent/candidate pair).
#
# Supplying their real dispersion matters: deflation scales with how much
# Sharpe varied across the search, and the library's fallback estimate is
# nearly insensitive to the trial count, which makes DSR look robust for the
# wrong reason. The observed spread here is wide (-0.72 to 0.77), so using it
# deflates HARDER than the default -- the sceptical direction, which is the
# one to report.
OBSERVED_TRIAL_SHARPES = (
    0.67,            # full mix (prior incumbent)
    0.33, 0.60, -0.72, 0.63,   # standalone: breadth, research, trend, momrank
    0.77, 0.51, 0.65, 0.60,    # leave-one-out: minus each of the four
    0.63,            # momentum-rank top-10 variant (failed its gate)
    0.63, 0.70,      # holdout incumbent, holdout candidate
)


def stats_for(equity: pd.Series, bench_sr: float) -> dict:
    """Raw, probabilistic and deflated Sharpe for one equity curve."""
    r = equity.pct_change().dropna().to_numpy()
    out = {
        "sharpe": metrics(equity, "x")["Sharpe"],
        "psr_vs_0": probabilistic_sharpe_ratio(r, 0.0),
        "psr_vs_bench": probabilistic_sharpe_ratio(r, bench_sr),
        "n_days": len(r),
    }
    for n in TRIAL_COUNTS:
        out[f"dsr_{n}"] = deflated_sharpe_ratio(r, n_trials=n)
    # Same deflation, but using the Sharpe dispersion this project actually
    # produced instead of the library's generic fallback. This is the figure
    # to quote: it reflects how wide the search really was.
    #
    # UNITS: deflated_sharpe_ratio expects PER-PERIOD variance -- its own
    # fallback is built from sharpe_ratio(r, 1) and it re-annualises the
    # resulting threshold. OBSERVED_TRIAL_SHARPES are annualised, so their
    # variance must be divided by periods per year. Passing the annualised
    # variance straight in overstates the hurdle by 252x and drives DSR to
    # exactly 0.000, which reads as a catastrophic result rather than the
    # unit error it is.
    var_annual = float(np.var(OBSERVED_TRIAL_SHARPES, ddof=1))
    var_period = var_annual / TRADING_DAYS
    out["trial_sr_var"] = var_annual
    out["dsr_observed"] = deflated_sharpe_ratio(
        r, n_trials=len(OBSERVED_TRIAL_SHARPES), sr_variance_across_trials=var_period)
    return out


async def amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--rebuild-bars", action="store_true")
    args = p.parse_args()

    from app.agents.front_office.strategy.sleeves import momentum_rank
    momentum_rank._TOP_N = 3

    config_universe = get_universe("config")
    pit = union_members("2008-01-01", "2024-12-31")
    anchor_bases = {_base(a) for a in _ANCHORS}
    tickers = list(_ANCHORS) + sorted(t for t in pit if t not in anchor_bases)

    # period="max": a 10y fetch from 2026 does not reach 2008 and would yield a
    # silently empty holdout, the trap validate_holdout_gate.py documents.
    cache = PAPER_DIR / "debate_ab_bars_max.pkl"
    if cache.exists() and not args.rebuild_bars:
        bars = pd.read_pickle(cache)
        print(f"Loaded {len(bars)} cached series from {cache.name}")
    else:
        print(f"Fetching {len(tickers)} tickers, period=max ...")
        bars = await fetch_batch(tickers, period="max")
        PAPER_DIR.mkdir(exist_ok=True)
        pd.to_pickle(bars, cache)
        print(f"Coverage: {len(bars)}/{len(tickers)} -> cached")

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"

    rows: list[tuple[str, dict]] = []
    for label, (start, end) in WINDOWS.items():
        win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
        cal = closes.index[win]
        # Guard the exact trap the holdout harness documents: an empty or
        # truncated window would silently produce a confident wrong number.
        assert len(cal) > 400, f"{label}: only {len(cal)} bars — fetch did not span it"
        spy = closes[spy_col].loc[cal[0]:cal[-1]].dropna()
        assert spy.index[0] <= pd.Timestamp(start) + pd.Timedelta(days=7), (
            f"{label}: SPY starts {spy.index[0].date()}, after the window start")

        print(f"\nRunning production mix over {label} ({len(cal)} bars)...")
        eq, _ = run(LIVE_CFG, PROD_WEIGHTS, bars, closes, opens, cal,
                    args.capital, config_universe)
        bench_sr = metrics((spy / spy.iloc[0]) * args.capital, "spy")["Sharpe"]
        s = stats_for(eq.reindex(cal).dropna(), bench_sr)
        s["bench_sr"] = bench_sr
        rows.append((label, s))

    print(f"\n{'window':22s} {'days':>5s} {'SR':>6s} {'PSR>0':>7s} "
          f"{'PSR>SPY':>8s} " + " ".join(f"{'DSR N=' + str(n):>9s}" for n in TRIAL_COUNTS)
          + f" {'DSR obs':>9s}")
    for label, s in rows:
        dsr = " ".join(f"{s[f'dsr_{n}']:>9.3f}" for n in TRIAL_COUNTS)
        print(f"{label:22s} {s['n_days']:>5d} {s['sharpe']:>6.2f} "
              f"{s['psr_vs_0']:>7.3f} {s['psr_vs_bench']:>8.3f} {dsr} "
              f"{s['dsr_observed']:>9.3f}")
    print(f"\nDSR obs uses the {len(OBSERVED_TRIAL_SHARPES)} Sharpe ratios this "
          f"project actually produced (variance {rows[0][1]['trial_sr_var']:.4f}, "
          f"range {min(OBSERVED_TRIAL_SHARPES)} to {max(OBSERVED_TRIAL_SHARPES)}), "
          f"rather than\nthe library's generic fallback -- a wider observed "
          f"spread deflates harder, so this is the sceptical figure.")

    print("\nReading: PSR>0 is the probability the true Sharpe is positive once")
    print("skew and kurtosis are accounted for. PSR>SPY is the same against the")
    print("benchmark's Sharpe. DSR deflates for having chosen the best of N")
    print("trials -- higher N is the more sceptical reading, and is the one to")
    print("quote if a reviewer disputes how many variants were evaluated.")

    lines = [r"% deflated / probabilistic Sharpe -- paste into Sec. VI",
             r"Window & Days & SR & PSR$>$0 & PSR$>$SPY & DSR \\"]
    for label, s in rows:
        lines.append(
            f"{label} & {s['n_days']} & {s['sharpe']:.2f} & "
            f"{s['psr_vs_0']:.3f} & {s['psr_vs_bench']:.3f} & "
            f"{s['dsr_observed']:.3f} " + r"\\")
    out = PAPER_DIR / "deflated_sharpe_table.tex"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")


def _selfcheck() -> None:
    """Check the metric wiring on constructed series -- no data, no network."""
    idx = pd.date_range("2020-01-01", periods=800, freq="B")
    # Deterministic mild uptrend with noise: positive but not absurd Sharpe.
    steps = np.array([0.0006 + 0.008 * np.sin(i * 1.7) for i in range(len(idx))])
    eq = pd.Series(100_000 * np.cumprod(1 + steps), index=idx)
    s = stats_for(eq, bench_sr=0.0)
    assert 0.0 <= s["psr_vs_0"] <= 1.0, s
    for n in TRIAL_COUNTS:
        assert 0.0 <= s[f"dsr_{n}"] <= 1.0, (n, s)
    # Deflation must be monotone: more trials searched -> weaker evidence.
    assert s["dsr_5"] >= s["dsr_20"] >= s["dsr_50"], s
    # Units guard. The observed-dispersion DSR must sit in the same regime as
    # the fallback, not collapse to zero -- an annualised variance passed where
    # a per-period one belongs inflates the hurdle 252x and silently reports a
    # catastrophic-looking 0.000.
    assert 0.0 <= s["dsr_observed"] <= 1.0, s
    hurdle_annual = math.sqrt(s["trial_sr_var"])
    assert hurdle_annual > 0.1, "observed trial Sharpes should have real spread"
    r = eq.pct_change().dropna().to_numpy()
    lo = deflated_sharpe_ratio(r, n_trials=12,
                               sr_variance_across_trials=s["trial_sr_var"] / 252)
    hi = deflated_sharpe_ratio(r, n_trials=12,
                               sr_variance_across_trials=s["trial_sr_var"])
    assert lo > hi, (lo, hi)  # per-period units must deflate less than annualised
    assert abs(s["dsr_observed"] - lo) < 1e-9, (s["dsr_observed"], lo)
    # A higher benchmark must never be easier to beat than a lower one.
    assert probabilistic_sharpe_ratio(eq.pct_change().dropna().to_numpy(), 2.0) <= \
        probabilistic_sharpe_ratio(eq.pct_change().dropna().to_numpy(), 0.0)
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        asyncio.run(amain())
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 66E43B19BEEA - verify with scripts/authorship.py verify
