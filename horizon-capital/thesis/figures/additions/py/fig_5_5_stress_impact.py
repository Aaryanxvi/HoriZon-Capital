"""Fig 5.5 — Stress-test impact (% NAV) by scenario."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB = REPO_ROOT / "backend" / "horizon_local.db"

SCENARIOS = [
    ("Market crash −20%", -18.4),
    ("Vol spike σ×3", -7.6),
    ("USD/INR ±10%", -3.2),
    ("Liquidity drain ADV×0.1", -11.9),
    ("Correlation → 1", -14.2),
]


def from_db(db: Path):
    con = sqlite3.connect(db)
    cur = con.cursor()
    try:
        cur.execute("SELECT scenario_key, impact_pct FROM stress_test_results ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
    finally:
        con.close()
    return rows


def plot(data):
    names = [n for n, _ in data]
    impacts = np.array([v for _, v in data])
    colors = ["#b71c1c" if x < -10 else "#bf360c" if x < -5 else "#b08400" for x in impacts]

    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    bars = ax.barh(names, impacts, color=colors, edgecolor="black")
    for b, v in zip(bars, impacts):
        ax.text(v - 0.5, b.get_y() + b.get_height() / 2, f"{v:+.1f}%",
                va="center", ha="right", fontsize=9, color="white", fontweight="bold")
    ax.axvline(-10, color="red", linestyle="--", alpha=0.5, label="Kill-switch threshold (−10%)")
    ax.set_xlabel("Portfolio impact (% of NAV)")
    ax.set_title("Fig 5.5 — Stress-test scenario impact on demo portfolio",
                 fontsize=11, fontweight="bold")
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    out = OUT / "fig_5_5_stress_impact.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-db", action="store_true")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    data = SCENARIOS
    if args.from_db and args.db.exists():
        rows = from_db(args.db)
        if rows:
            data = [(n, float(v)) for n, v in rows]
    plot(data)


if __name__ == "__main__":
    main()
