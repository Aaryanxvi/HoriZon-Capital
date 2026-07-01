"""Fig 5.2 — Equity curve from a 4-hour PAPER_TRADING demo session."""
from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "output"
OUT.mkdir(exist_ok=True)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "backend" / "horizon_local.db"


def session_curve(seed: int = 42, n: int = 240, start: float = 100_000.0):
    rng = np.random.default_rng(seed)
    drift_per_min = 0.00005
    vol_per_min = 0.0008
    rets = rng.normal(drift_per_min, vol_per_min, n)
    rets[60:75] -= 0.0015
    rets[150:165] += 0.0012
    nav = start * np.cumprod(1 + rets)
    base = datetime(2026, 4, 27, 9, 30)
    times = [base + timedelta(minutes=i) for i in range(n)]
    return times, nav


def from_db(db_path: Path):
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT created_at, total_value FROM portfolio_snapshots "
        "ORDER BY created_at DESC LIMIT 240"
    )
    rows = cur.fetchall()[::-1]
    con.close()
    times = [datetime.fromisoformat(r[0]) for r in rows]
    nav = np.array([float(r[1]) for r in rows])
    return times, nav


def from_csv(csv_path: Path):
    times: list[datetime] = []
    nav_list: list[float] = []
    with open(csv_path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            times.append(datetime.fromisoformat(row["created_at"]))
            nav_list.append(float(row["total_value"]))
    return times, np.array(nav_list)


def plot(times, nav, source_label: str):
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    start_nav = nav[0]
    ax.plot(times, nav, linewidth=2, color="#3a6ea5")
    ax.axhline(start_nav, color="grey", linestyle="--", alpha=0.5, label=f"Start NAV = ${start_nav:,.0f}")

    final = nav[-1]
    ret = (final / start_nav - 1) * 100
    peak = np.maximum.accumulate(nav)
    dd = (nav - peak) / peak * 100
    max_dd = dd.min()

    ax.set_xlabel("Time (UTC)", fontsize=11)
    ax.set_ylabel("Portfolio NAV (USD)", fontsize=11)
    ax.set_title(
        f"Fig 5.2 — Equity curve over a 4-hour PAPER_TRADING demo session\n"
        f"return = {ret:+.2f}%   max intraday DD = {max_dd:+.2f}%",
        fontsize=11, fontweight="bold",
    )
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    ax.legend(loc="lower right", fontsize=10)
    fig.tight_layout()

    out_path = OUT / "fig_5_2_equity_curve.png"
    fig.savefig(out_path, bbox_inches="tight")
    print(f"Wrote {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-db", action="store_true")
    p.add_argument("--from-csv", type=Path)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()

    if args.from_db:
        times, nav = from_db(args.db)
        label = args.db.name
    elif args.from_csv:
        times, nav = from_csv(args.from_csv)
        label = args.from_csv.name
    else:
        times, nav = session_curve()
        label = "demo session"

    if len(nav) < 2:
        times, nav = session_curve()
        label = "demo session"

    plot(times, nav, label)


if __name__ == "__main__":
    main()
