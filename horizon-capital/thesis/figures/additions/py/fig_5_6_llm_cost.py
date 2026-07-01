"""Fig 5.6 — LLM cost stack per agent (USD over 4-hour demo)."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

AGENTS = ["StrategyAgent", "DebateAgent", "CIOAgent", "IRAgent"]
INPUT_USD = np.array([0.18, 1.42, 0.86, 0.32])
OUTPUT_USD = np.array([0.04, 2.81, 1.74, 0.55])


def plot():
    x = np.arange(len(AGENTS))
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.bar(x, INPUT_USD, label="Input tokens cost", color="#3a6ea5", edgecolor="black")
    ax.bar(x, OUTPUT_USD, bottom=INPUT_USD, label="Output tokens cost", color="#bf360c", edgecolor="black")
    totals = INPUT_USD + OUTPUT_USD
    for i, t in enumerate(totals):
        ax.text(i, t + 0.05, f"${t:.2f}", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(AGENTS)
    ax.set_ylabel("USD")
    ax.set_title(f"Fig 5.6 — LLM cost stack per agent (4-hour demo, total ${totals.sum():.2f})",
                 fontsize=11, fontweight="bold")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    out = OUT / "fig_5_6_llm_cost.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    plot()
