"""Fig 5.1 — Distribution of 368 test cases by module.

Counts derived from `pytest --collect-only` on backend/tests at audit time.
Edit the dict below if you re-run collection and numbers shift.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

modules = {
    "smoke": 232,
    "integration": 69,
    "cio (8 files)": 24,
    "paper_trading_honest": 11,
    "e2e_paper_trading_smoke": 7,
    "critical_fixes": 9,
    "trades_command": 5,
    "yahoo_1min": 4,
    "alpaca_feed": 3,
    "settings_panel": 4,
}
total = sum(modules.values())

names = list(modules.keys())
counts = list(modules.values())
colors = plt.cm.viridis([i / len(names) for i in range(len(names))])

fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
bars = ax.barh(names, counts, color=colors, edgecolor="black")
ax.invert_yaxis()
ax.set_xlabel("Number of test functions", fontsize=11)
ax.set_title(
    f"Fig 5.1 — Test distribution by module ({total} of 368 collected)",
    fontsize=12, fontweight="bold",
)
for bar, count in zip(bars, counts):
    ax.text(
        bar.get_width() + 2, bar.get_y() + bar.get_height() / 2,
        str(count), va="center", fontsize=10,
    )
ax.grid(axis="x", alpha=0.3)
fig.tight_layout()

out_path = OUT / "fig_5_1_test_distribution.png"
fig.savefig(out_path, bbox_inches="tight")
print(f"Wrote {out_path}")
