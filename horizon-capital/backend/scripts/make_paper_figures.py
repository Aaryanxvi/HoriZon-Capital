# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-1DC9B778866C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Equity-curve figures for the paper.

Two figures, both single-column width for a two-column IEEE layout:

  fig_equity.pdf   production mix against the S&P 500 on each evaluation
                   window -- the strategy result
  fig_gate.pdf     the debate-gate experiment: ungated against gated, with the
                   spread of rate-matched random gates drawn behind them, which
                   is the comparison the paper turns on

Design choices that are not decoration:

* Colours are the validated categorical slots (blue #2a78d6, orange #eb6834);
  the pair clears protan, deutan and tritan separation. The benchmark is drawn
  in neutral grey because it is a reference line, not a competing series.
* Every series also differs in DASH PATTERN. Papers get printed in black and
  white, and a reader with one of the common colour deficiencies should not
  have to take the colour on trust. Colour is never the only encoding here.
* Lines are labelled at their right-hand end rather than in a legend box, so
  identity is read where the eye already is.
* Curves are normalised to 100 at the window start: the question is relative
  path, and equal starting points make the divergence legible.
* The random-gate band is drawn as a filled 5th-95th percentile envelope. Its
  point is that the gated line sits INSIDE it.

Usage:
    python scripts/make_paper_figures.py
    python scripts/make_paper_figures.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.validate_debate_ab import (  # noqa: E402
    PAPER_DIR,
    PROD_WEIGHTS,
    _cache_key,
    execute,
)
from scripts.validate_sleeve_attribution import LIVE_CFG, metrics, run  # noqa: E402

BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#8a8a86"
GRID = "#dcdcd8"
INK, MUTED = "#0b0b0b", "#5c5c58"

plt.rcParams.update({
    "font.size": 7.5,
    "font.family": "serif",
    "axes.linewidth": 0.6,
    "axes.edgecolor": MUTED,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "figure.dpi": 200,
})


def _style_axes(ax) -> None:
    """Recessive frame: no top/right spines, a faint horizontal grid only."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


def _label_end(ax, series: pd.Series, text: str, color: str, dy: float = 0.0) -> None:
    """Name the line at its right end instead of in a legend box."""
    ax.annotate(text, xy=(series.index[-1], series.iloc[-1]),
                xytext=(4, dy), textcoords="offset points",
                color=color, fontsize=7, va="center", weight="bold")


def _norm(eq: pd.Series) -> pd.Series:
    return eq / eq.iloc[0] * 100.0


def figure_equity(bars_max, out: Path) -> dict:
    """Production mix vs the index on both evaluation windows."""
    from app.data_layer.universe import get_universe

    closes = pd.DataFrame({s: df["close"] for s, df in bars_max.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars_max.items()}).sort_index()
    spy_col = "SPY.NYSE" if "SPY.NYSE" in closes.columns else "SPY"
    cfg_uni = get_universe("config")

    windows = [("Selection: 2018--2024", "2018-01-01", "2024-12-31"),
               ("Holdout: 2008--2017", "2008-01-01", "2017-12-31")]
    fig, axes = plt.subplots(2, 1, figsize=(3.4, 4.0), sharex=False)
    summary = {}

    for ax, (title, start, end) in zip(axes, windows, strict=True):
        win = (closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))
        cal = closes.index[win]
        eq, _ = run(LIVE_CFG, PROD_WEIGHTS, bars_max, closes, opens, cal, 100_000.0, cfg_uni)
        eq = eq.reindex(cal).dropna()
        spy = closes[spy_col].loc[eq.index[0]:eq.index[-1]].dropna()

        mix_n, spy_n = _norm(eq), _norm(spy)
        ax.plot(spy_n.index, spy_n.values, color=GREY, lw=1.0, ls=(0, (1, 1.6)), zorder=2)
        ax.plot(mix_n.index, mix_n.values, color=BLUE, lw=1.3, ls="-", zorder=3)
        # Plain text, not LaTeX: matplotlib does not interpret TeX escapes here,
        # so "S\&P" would print the backslash.
        _label_end(ax, spy_n, "S&P 500", GREY)
        _label_end(ax, mix_n, "Mix", BLUE)

        _style_axes(ax)
        ax.set_title(title.replace("--", "–"), fontsize=7.5, color=INK,
                     loc="left", pad=3)
        ax.set_ylabel("Index (start = 100)", fontsize=7, color=MUTED)
        # Only enough right margin to seat the end labels; the default left a
        # year of empty axis on each side.
        ax.set_xlim(mix_n.index[0], mix_n.index[-1] + pd.Timedelta(days=340))
        # A ten-year window at column width cannot carry a label per year --
        # they run together into an unreadable digit string. Every other year.
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        summary[title] = {"mix_sharpe": metrics(eq, "m")["Sharpe"],
                          "spy_sharpe": metrics(spy, "s")["Sharpe"]}

    fig.tight_layout(pad=0.4)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return summary


def figure_gate(out: Path) -> dict:
    """Ungated vs gated, over the spread of rate-matched random gates."""
    bars = pd.read_pickle(PAPER_DIR / "debate_ab_bars_2018_2024.pkl")
    stream = json.loads((PAPER_DIR / "debate_ab_stream_2018_2024.json")
                        .read_text(encoding="utf-8"))
    signals = [r for r in stream if "targets_snapshot" not in r]

    verdicts: dict[str, dict] = {}
    for line in (PAPER_DIR / "debate_ab_verdicts_blind.jsonl").read_text(
            encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("decision") == "ERROR":
            verdicts.pop(r["key"], None)
        else:
            verdicts[r["key"]] = r

    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    win = (closes.index >= pd.Timestamp("2018-01-01")) & \
          (closes.index <= pd.Timestamp("2024-12-31"))
    cal = closes.index[win]

    eq_a, _, info_a = execute(stream, None, "blind", closes, opens, cal, 100_000.0)
    eq_b, _, info_b = execute(stream, verdicts, "blind", closes, opens, cal,
                              100_000.0, "passthrough")

    # Rebuild the random-gate envelope from the same machinery the paper used,
    # so the band and Table VI cannot disagree.
    judged = [s for s in signals if _cache_key("blind", s) in verdicts]
    rate = sum(1 for s in judged
               if verdicts[_cache_key("blind", s)]["decision"] == "REJECTED") / len(judged)
    curves = []
    for trial in range(25):
        import hashlib
        fake = {}
        for sig in judged:
            k = _cache_key("blind", sig)
            h = int(hashlib.sha1(f"{trial}|{k}".encode()).hexdigest()[:8], 16)
            fake[k] = {"decision": "APPROVED" if (h % 10_000) / 10_000.0 >= rate
                       else "REJECTED", "mode": "blind"}
        eq, _, _ = execute(stream, fake, "blind", closes, opens, cal, 100_000.0,
                           "passthrough")
        curves.append(_norm(eq.reindex(cal).ffill()))

    band = pd.concat(curves, axis=1)
    lo, hi = band.quantile(0.05, axis=1), band.quantile(0.95, axis=1)

    fig, ax = plt.subplots(figsize=(3.4, 2.3))
    ax.fill_between(lo.index, lo.values, hi.values, color=GREY, alpha=0.22,
                    linewidth=0, zorder=1)
    a_n, b_n = _norm(eq_a.reindex(cal).dropna()), _norm(eq_b.reindex(cal).dropna())
    ax.plot(a_n.index, a_n.values, color=BLUE, lw=1.3, ls="-", zorder=3)
    ax.plot(b_n.index, b_n.values, color=ORANGE, lw=1.3, ls=(0, (4, 1.6)), zorder=3)
    _label_end(ax, a_n, "No gate", BLUE, dy=4)
    _label_end(ax, b_n, "Gate on", ORANGE, dy=-4)

    _style_axes(ax)
    ax.set_ylabel("Index (start = 100)", fontsize=7, color=MUTED)
    ax.set_title("Debate gate vs. no gate", fontsize=7.5, color=INK, loc="left",
                 pad=3)
    ax.annotate("shaded: 5th–95th pct of 25\nrate-matched random gates",
                xy=(0.03, 0.95), xycoords="axes fraction", fontsize=6.2,
                color=MUTED, va="top")
    ax.set_xlim(a_n.index[0], a_n.index[-1] + pd.Timedelta(days=360))
    fig.tight_layout(pad=0.4)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)

    return {"a_sharpe": metrics(eq_a.dropna(), "a")["Sharpe"],
            "b_sharpe": metrics(eq_b.dropna(), "b")["Sharpe"],
            "a_fills": info_a["fills"], "b_fills": info_b["fills"],
            "reject_rate": rate,
            "b_inside_band": bool(lo.iloc[-1] <= b_n.iloc[-1] <= hi.iloc[-1])}


def main() -> None:
    p = argparse.ArgumentParser()
    p.parse_args()

    from app.agents.front_office.strategy.sleeves import momentum_rank
    momentum_rank._TOP_N = 3

    print("Figure 2: equity curves, both windows ...")
    bars_max = pd.read_pickle(PAPER_DIR / "debate_ab_bars_max.pkl")
    s = figure_equity(bars_max, PAPER_DIR / "fig_equity.pdf")
    for k, v in s.items():
        print(f"  {k}: mix Sharpe {v['mix_sharpe']}, SPY {v['spy_sharpe']}")

    print("Figure 3: debate gate ...")
    g = figure_gate(PAPER_DIR / "fig_gate.pdf")
    print(f"  arm A Sharpe {g['a_sharpe']} ({g['a_fills']} fills), "
          f"arm B {g['b_sharpe']} ({g['b_fills']} fills), "
          f"rejection {g['reject_rate']:.1%}")
    print(f"  gated curve ends inside the random-gate band: {g['b_inside_band']}")
    print(f"\nWrote {PAPER_DIR / 'fig_equity.pdf'} and {PAPER_DIR / 'fig_gate.pdf'}")


def _selfcheck() -> None:
    """Check the plotting helpers on synthetic series -- no data, no network."""
    idx = pd.date_range("2020-01-01", periods=50, freq="B")
    s = pd.Series(np.linspace(100.0, 200.0, 50), index=idx)
    n = _norm(s)
    assert abs(n.iloc[0] - 100.0) < 1e-9, n.iloc[0]
    assert abs(n.iloc[-1] - 200.0) < 1e-9, n.iloc[-1]
    # Normalisation must preserve shape, only rescale.
    assert np.allclose((n / n.iloc[0]).values, (s / s.iloc[0]).values)

    fig, ax = plt.subplots()
    ax.plot(n.index, n.values)
    _style_axes(ax)
    assert not ax.spines["top"].get_visible()
    assert not ax.spines["right"].get_visible()
    _label_end(ax, n, "x", BLUE)
    assert len(ax.texts) == 1
    plt.close(fig)

    # The two series colours must be the validated categorical slots, not
    # whatever matplotlib would have cycled to.
    assert BLUE == "#2a78d6" and ORANGE == "#eb6834"
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 1DC9B778866C - verify with scripts/authorship.py verify
