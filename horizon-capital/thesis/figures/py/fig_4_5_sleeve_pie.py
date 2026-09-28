# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-3B49AAA4F585
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 4.5 — Strategy sleeve allocation pie.

Allocations from strategy_agent.py lines 88-91.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

labels = [
    "Research Stack\n(HRP + ½-Kelly + GMM + Quality)",
    "Trend Filter\n(Faber 200d on SPY)",
    "Gap Fade\n(overnight on QQQ)",
    "Momentum Rank\n(12 − 1 cross-sectional)",
]
sizes = [60, 20, 10, 10]
colors = ["#3a6ea5", "#b08400", "#2e7d32", "#6a1b9a"]
explode = [0.03, 0.02, 0.02, 0.02]

fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
wedges, _, autotexts = ax.pie(
    sizes,
    labels=labels,
    autopct="%1.0f%%",
    explode=explode,
    colors=colors,
    startangle=90,
    pctdistance=0.75,
    wedgeprops={"edgecolor": "white", "linewidth": 2},
    textprops={"fontsize": 10},
)
for txt in autotexts:
    txt.set_color("white")
    txt.set_fontweight("bold")
    txt.set_fontsize(11)

ax.set_title("Fig 4.5 — Strategy sleeve allocation", fontsize=12, fontweight="bold")
fig.tight_layout()

out_path = OUT / "fig_4_5_sleeve_pie.png"
fig.savefig(out_path, bbox_inches="tight")
print(f"Wrote {out_path}")
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 3B49AAA4F585 - verify with scripts/authorship.py verify
