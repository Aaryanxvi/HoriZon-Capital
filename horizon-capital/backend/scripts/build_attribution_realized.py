# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-CF20FBC19BA1
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Re-run the sleeve attribution against the realized risk-free series.

Tables I and V now use the realized bill rate. The attribution table still
carried ratios computed against a flat 4%, which would leave the paper quoting
two different definitions of the same statistic.

There is a substantive question underneath the bookkeeping. The decision to
drop the breadth sleeve was made under the flat rate. If the verdicts change
under the corrected one, that is a finding and has to be reported; if they do
not, the original decision stands on firmer ground than it did. Either way the
recomputation happens before we know which.

Usage:
    python scripts/build_attribution_realized.py
    python scripts/build_attribution_realized.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_results import PAPER_DIR, metric_suite  # noqa: E402
from scripts.validate_riskfree import load_riskfree  # noqa: E402
from scripts.validate_sleeve_attribution import (  # noqa: E402
    LIVE_CFG,
    LIVE_WEIGHTS,
    _loo_weights,
    run,
)

# Pre-registered thresholds, unchanged from the original attribution run.
DRAG_MARGIN, CARRY_MARGIN = 0.03, 0.05


def verdict(loo_sharpe: float, full_sharpe: float) -> str:
    if loo_sharpe >= full_sharpe + DRAG_MARGIN:
        return "drags"
    if loo_sharpe <= full_sharpe - CARRY_MARGIN:
        return "carries"
    return "neutral"


def main() -> None:
    argparse.ArgumentParser().parse_args()

    from app.agents.front_office.strategy.sleeves import momentum_rank
    from app.data_layer.universe import get_universe
    momentum_rank._TOP_N = 3

    rf = load_riskfree()
    bars = pd.read_pickle(PAPER_DIR / "debate_ab_bars_max.pkl")
    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    cfg_uni = get_universe("config")
    win = (closes.index >= pd.Timestamp("2018-01-01")) & \
          (closes.index <= pd.Timestamp("2024-12-31"))
    cal = closes.index[win]

    def sharpe_of(weights: dict) -> tuple[float, float]:
        eq, _ = run(LIVE_CFG, weights, bars, closes, opens, cal, 100_000.0, cfg_uni)
        m = metric_suite(eq.reindex(cal).dropna(), rf)
        return m["sharpe"], m["max_dd_pct"]

    print("full mix ...")
    full_sr, _ = sharpe_of(LIVE_WEIGHTS)
    rows = {}
    for name in LIVE_WEIGHTS:
        print(f"standalone {name} ...")
        solo_sr, solo_dd = sharpe_of({name: 1.0})
        print(f"LOO minus {name} ...")
        loo_sr, _ = sharpe_of(_loo_weights(name))
        rows[name] = {"solo_sharpe": solo_sr, "solo_maxdd": solo_dd,
                      "loo_sharpe": loo_sr, "verdict": verdict(loo_sr, full_sr)}

    print(f"\nfull-mix Sharpe (realized rf) = {full_sr:.2f}")
    print(f"{'sleeve':18s} {'solo SR':>8s} {'solo DD%':>9s} {'LOO SR':>7s} "
          f"{'delta':>7s}  verdict")
    for name, r in rows.items():
        print(f"{name:18s} {r['solo_sharpe']:>8.2f} {r['solo_maxdd']:>9.1f} "
              f"{r['loo_sharpe']:>7.2f} {r['loo_sharpe'] - full_sr:>+7.2f}  "
              f"{r['verdict']}")

    out = PAPER_DIR / "attribution_realized.json"
    out.write_text(json.dumps({"full_sharpe": full_sr, "sleeves": rows},
                              indent=1, default=float), encoding="utf-8")
    print(f"\nWrote {out}")


def _selfcheck() -> None:
    """The verdict rule must reproduce the original run's classifications."""
    full = 0.67
    # Original flat-rate results: breadth 0.77, research 0.51, trend 0.65,
    # momrank 0.60.
    assert verdict(0.77, full) == "drags"
    assert verdict(0.51, full) == "carries"
    assert verdict(0.65, full) == "neutral"
    assert verdict(0.60, full) == "carries"
    # Boundaries are inclusive exactly as pre-registered.
    assert verdict(full + DRAG_MARGIN, full) == "drags"
    assert verdict(full - CARRY_MARGIN, full) == "carries"
    assert verdict(full, full) == "neutral"
    assert abs(np.float64(1.0) - 1.0) < 1e-12
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token CF20FBC19BA1 - verify with scripts/authorship.py verify
