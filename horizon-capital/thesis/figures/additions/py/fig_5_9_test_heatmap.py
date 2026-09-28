# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-88F1D47F35AC
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 5.9 — Test pass/fail heatmap (module × status)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

MODULES = [
    "test_smoke", "test_integration", "test_cio_*", "test_paper_trading_honest",
    "test_critical_fixes", "test_e2e_paper_trading_smoke", "test_trades_command",
    "test_settings_panel", "test_yahoo_1min", "test_alpaca_feed",
    "test_performance", "test_sentiment", "test_simple_strategies",
    "test_trading_lifecycle", "test_debate_hardening",
]
PASS = [232, 69, 24, 11, 9, 7, 5, 4, 4, 3, 0, 0, 0, 0, 0]
FAIL = [0] * 15
ERR =  [0]*10 + [1]*5


def plot():
    data = np.array([PASS, FAIL, ERR])
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    norm = data / np.maximum(data.max(axis=0), 1)
    im = ax.imshow(norm, aspect="auto", cmap="RdYlGn_r")
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["Pass", "Fail", "Errored"])
    ax.set_xticks(range(len(MODULES)))
    ax.set_xticklabels(MODULES, rotation=45, ha="right", fontsize=8)
    for i in range(3):
        for j in range(len(MODULES)):
            v = data[i, j]
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center",
                        color="white" if norm[i, j] > 0.5 else "black", fontsize=8)
    ax.set_title("Fig 5.9 — Per-module test outcomes (368 collected)",
                 fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, label="Normalised count (per row)")
    fig.tight_layout()
    out = OUT / "fig_5_9_test_heatmap.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    plot()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 88F1D47F35AC - verify with scripts/authorship.py verify
