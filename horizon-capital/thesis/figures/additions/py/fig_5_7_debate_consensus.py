# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-F96555D2CAD5
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 5.7 — Debate consensus-score histogram with APPROVE/REJECT split."""
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


def synthetic(seed: int = 13, n: int = 120):
    rng = np.random.default_rng(seed)
    approved = rng.beta(8, 3, int(n * 0.7))
    rejected = rng.beta(3, 6, n - len(approved))
    return approved, rejected


def from_db(db: Path):
    con = sqlite3.connect(db)
    cur = con.cursor()
    try:
        cur.execute("SELECT consensus_score, final_decision FROM debate_sessions WHERE consensus_score IS NOT NULL")
        rows = cur.fetchall()
    finally:
        con.close()
    if not rows:
        return None, None
    approved = np.array([r[0] for r in rows if r[1] == "APPROVED"])
    rejected = np.array([r[0] for r in rows if r[1] != "APPROVED"])
    return approved, rejected


def plot(approved, rejected):
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    bins = np.linspace(0, 1, 21)
    ax.hist(approved, bins=bins, alpha=0.7, color="#2e7d32", label=f"APPROVED (n={len(approved)})", edgecolor="black")
    ax.hist(rejected, bins=bins, alpha=0.7, color="#b71c1c", label=f"REJECTED (n={len(rejected)})", edgecolor="black")
    ax.axvline(0.6, color="black", linestyle="--", label="Approval threshold = 0.60")
    ax.set_xlabel("Consensus score")
    ax.set_ylabel("Debate count")
    ax.set_title("Fig 5.7 — Distribution of debate consensus scores",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = OUT / "fig_5_7_debate_consensus.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-db", action="store_true")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    if args.from_db and args.db.exists():
        a, r = from_db(args.db)
        if a is not None and len(a) + len(r) > 0:
            plot(a, r)
            return
    a, r = synthetic()
    plot(a, r)


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token F96555D2CAD5 - verify with scripts/authorship.py verify
