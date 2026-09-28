# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-875996F41803
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Fig 5.8 — Drawdown timeline with kill-switch threshold."""
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


def synthetic(seed: int = 19, n: int = 240):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.00005, 0.0008, n)
    rets[60:90] -= 0.0025
    nav = 100_000 * np.cumprod(1 + rets)
    peak = np.maximum.accumulate(nav)
    dd = (nav - peak) / peak * 100
    base = datetime(2026, 4, 27, 9, 30)
    times = [base + timedelta(minutes=i) for i in range(n)]
    return times, dd


def from_db(db: Path):
    con = sqlite3.connect(db)
    cur = con.cursor()
    try:
        cur.execute("SELECT created_at, current_drawdown FROM risk_metrics ORDER BY created_at")
        rows = cur.fetchall()
    finally:
        con.close()
    if not rows:
        return None, None
    times = [datetime.fromisoformat(r[0]) for r in rows]
    dd = -np.array([float(r[1]) for r in rows]) * 100
    return times, dd


def plot(times, dd):
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.fill_between(times, dd, 0, color="#bf360c", alpha=0.4)
    ax.plot(times, dd, color="#b71c1c", linewidth=1.5)
    ax.axhline(-10, color="red", linestyle="--", label="Kill-switch threshold (−10%)")
    ax.axhline(-7, color="orange", linestyle=":", label="CIO crisis warning (−7%)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Fig 5.8 — Drawdown timeline (4-hour demo)",
                 fontsize=11, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    out = OUT / "fig_5_8_drawdown_timeline.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"Wrote {out}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-db", action="store_true")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    if args.from_db and args.db.exists():
        t, d = from_db(args.db)
        if t:
            plot(t, d)
            return
    t, d = synthetic()
    plot(t, d)


if __name__ == "__main__":
    main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 875996F41803 - verify with scripts/authorship.py verify
