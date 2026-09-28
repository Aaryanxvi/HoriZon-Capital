# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-6028E4E973DF
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 5.3 — 46 audit gaps grouped by category and severity (P0/P1/P2)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

categories = [
    "Market data ingestion",
    "Signal generation",
    "Order lifecycle",
    "Fill realism",
    "Position & P&L",
    "Risk gates",
    "Persistence & restart",
    "Dashboard wiring",
    "Edge cases",
]
p0 = [2, 1, 1, 2, 2, 2, 3, 0, 1]
p1 = [3, 3, 3, 2, 3, 2, 4, 4, 2]
p2 = [1, 0, 0, 2, 1, 0, 0, 1, 1]
totals = [a + b + c for a, b, c in zip(p0, p1, p2)]

fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
x = np.arange(len(categories))

ax.barh(x, p0, color="#c0392b", label="P0 (blocker)", edgecolor="white")
ax.barh(x, p1, left=p0, color="#e67e22", label="P1 (should-have)", edgecolor="white")
ax.barh(
    x, p2,
    left=[a + b for a, b in zip(p0, p1)],
    color="#f1c40f",
    label="P2 (polish)", edgecolor="white",
)

for i, total in enumerate(totals):
    ax.text(total + 0.1, i, str(total), va="center", fontsize=10, fontweight="bold")

ax.set_yticks(x)
ax.set_yticklabels(categories, fontsize=10)
ax.invert_yaxis()
ax.set_xlabel("Number of gaps", fontsize=11)
ax.set_title(
    f"Fig 5.3 — 46 audit gaps grouped by category × severity\n"
    f"P0 = {sum(p0)}, P1 = {sum(p1)}, P2 = {sum(p2)}",
    fontsize=12, fontweight="bold",
)
ax.legend(loc="lower right", fontsize=10)
ax.grid(axis="x", alpha=0.3)
fig.tight_layout()

out_path = OUT / "fig_5_3_gap_distribution.png"
fig.savefig(out_path, bbox_inches="tight")
print(f"Wrote {out_path}")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 6028E4E973DF - verify with scripts/authorship.py verify
