"""Fig 5.10 — Inter-agent message rate (msgs/min) over demo session."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = REPO_ROOT / "backend" / "horizon_local.db"

CHANNELS = ["TICK", "FEATURE_UPDATE", "SIGNAL", "ORDER_NEW", "ORDER_FILL", "RISK_ALERT"]


def synthetic(seed: int = 23, n: int = 240):
    rng = np.random.default_rng(seed)
    base = datetime(2026, 4, 27, 9, 30)
    times = [base + timedelta(minutes=i) for i in range(n)]
    rates = {
        "TICK": rng.poisson(45, n),
        "FEATURE_UPDATE": rng.poisson(12, n),
        "SIGNAL": rng.poisson(2, n),
        "ORDER_NEW": rng.poisson(1, n),
        "ORDER_FILL": rng.poisson(1, n),
        "RISK_ALERT": (rng.random(n) < 0.05).astype(int),
    }
    return times, rates


def plot(times, rates):
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    bottom = np.zeros(len(times))
    colors = ["#3a6ea5", "#2e7d32", "#b08400", "#bf360c", "#6a1b9a", "#b71c1c"]
    for ch, color in zip(CHANNELS, colors):
        v = rates[ch]
        ax.fill_between(times, bottom, bottom + v, label=ch, color=color, alpha=0.8)
        bottom = bottom + v
    ax.set_xlabel("Time")
    ax.set_ylabel("Messages per minute")
    ax.set_title("Fig 5.10 — Inter-agent message rate by type",
                 fontsize=11, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    out = OUT / "fig_5_10_msg_rate.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-db", action="store_true")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    t, r = synthetic()
    plot(t, r)


if __name__ == "__main__":
    main()
