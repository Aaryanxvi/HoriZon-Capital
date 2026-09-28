# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D1796C364AF9
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Check that the numbers printed in the paper match the computed results.

A paper assembled over many runs drifts: a table gets recomputed, a sentence
quoting the same figure does not, and the mismatch survives every proofread
because both numbers look plausible. This script re-reads the harness outputs
and asserts that each headline figure still appears in the manuscript.

It is deliberately literal. It searches for the exact rendered string, so a
number that moved will fail here rather than in review.

Usage:
    python verify_numbers.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEX = HERE / "horizon_capital_paper_draft1.tex"


def load(name: str) -> dict | None:
    p = HERE / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    tex = TEX.read_text(encoding="utf-8")
    checks: list[tuple[str, str, bool]] = []

    def want(label: str, needle: str) -> None:
        checks.append((label, needle, needle in tex))

    results = load("results_all.json")
    if results:
        for key, m in results.items():
            window, row = key.split("/", 1)
            if row not in ("mix",):
                continue
            want(f"{window} mix CAGR", f"{m['cagr_pct']:.1f}\\%")
            want(f"{window} mix Sharpe", f"{m['sharpe']:.2f}")
            want(f"{window} mix Sortino", f"{m['sortino']:.2f}")
            want(f"{window} mix maxDD", f"{m['max_dd_pct']:.1f}\\%")
            want(f"{window} mix terminal",
                 "\\${:,}".format(round(m["terminal"])).replace(",", "{,}"))

    gate = load("gate_results_realized.json")
    if gate:
        want("arm A Sharpe", f"{gate['arm_a']['sharpe']:.2f}")
        want("arm B Sharpe", f"{gate['arm_b']['sharpe']:.2f}")
        want("arm C Sharpe", f"{gate['arm_c']['sharpe_mean']:.2f}")
        want("arm C sd", f"{gate['arm_c']['sharpe_std']:.2f}")
        want("arm A fills", f"{gate['arm_a_fills']:,}".replace(",", "{,}"))
        want("arm B fills", f"{gate['arm_b_fills']:,}".replace(",", "{,}"))
        want("reject rate", f"{gate['reject_rate'] * 100:.1f}\\%")
        want("arm B turnover", f"{gate['arm_b_turnover']:.2f}")
        for w, d in gate.get("deflated", {}).items():
            tag = w.split()[0].lower()
            want(f"{tag} DSR", f"{d['dsr']:.3f}")
            want(f"{tag} PSR>SPY", f"{d['psr_bench']:.3f}")

    attr = load("attribution_realized.json")
    if attr:
        want("attribution full-mix Sharpe", f"{attr['full_sharpe']:.2f}")
        for name, r in attr["sleeves"].items():
            want(f"attr {name} LOO", f"{r['loo_sharpe']:.2f}")

    peers = load("peer_results_realized.json")
    if peers:
        for key, m in peers.items():
            want(f"{key} Sharpe", f"{m['sharpe']:.2f}")

    width = max(len(c[0]) for c in checks) if checks else 10
    bad = 0
    for label, needle, ok in checks:
        if not ok:
            bad += 1
        print(f"  {'OK ' if ok else 'MISS'}  {label:{width}s}  {needle}")

    # A number appearing somewhere in a 9000-word paper is weak evidence, so
    # also flag figures that look like leftovers from the flat-rate draft.
    stale = [pat for pat in (r"0\.77 vs\.\\? 0\.55", r"0\.70 vs\.\\? 0\.31",
                             r"flat 4\\% risk-free rate is severe")
             if re.search(pat, tex)]
    print(f"\nchecked {len(checks)} figures, {bad} missing")
    if stale:
        print(f"stale flat-rate phrasing still present: {stale}")
    print("VERDICT:", "PASS" if bad == 0 and not stale else "NEEDS ATTENTION")
    return 1 if (bad or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D1796C364AF9 - verify with scripts/authorship.py verify
