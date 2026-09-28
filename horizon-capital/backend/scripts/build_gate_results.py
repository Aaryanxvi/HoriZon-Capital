# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-22A95EF4CB87
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Recompute the gate experiment and the deflated Sharpe against realized rates.

Tables I and III move when the risk-free assumption is corrected, so Table VI
and the deflated-Sharpe table have to move with them or the paper reports two
incompatible definitions of the same ratio. This recomputes both from the
cached verdicts and the cached bars, without a single provider request.

Usage:
    python scripts/build_gate_results.py
    python scripts/build_gate_results.py --selfcheck
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.quant.metrics_advanced import (  # noqa: E402
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from scripts.build_results import PAPER_DIR, metric_suite  # noqa: E402
from scripts.validate_debate_ab import _cache_key, execute  # noqa: E402
from scripts.validate_deflated_sharpe import OBSERVED_TRIAL_SHARPES  # noqa: E402
from scripts.validate_riskfree import load_riskfree  # noqa: E402

TRADING_DAYS = 252


def _excess_returns(eq: pd.Series, rf: pd.Series) -> np.ndarray:
    r = eq.pct_change().dropna()
    rf_d = (1.0 + rf.reindex(r.index).ffill().bfill()) ** (1 / TRADING_DAYS) - 1.0
    return (r - rf_d).to_numpy()


def main() -> None:
    argparse.ArgumentParser().parse_args()
    rf = load_riskfree()

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
    m_a = metric_suite(eq_a.dropna(), rf)
    m_b = metric_suite(eq_b.dropna(), rf)

    judged = [s for s in signals if _cache_key("blind", s) in verdicts]
    rate = sum(1 for s in judged
               if verdicts[_cache_key("blind", s)]["decision"] == "REJECTED") / len(judged)

    sharpes, fills = [], []
    for trial in range(25):
        fake = {}
        for sig in judged:
            k = _cache_key("blind", sig)
            h = int(hashlib.sha1(f"{trial}|{k}".encode()).hexdigest()[:8], 16)
            fake[k] = {"decision": "APPROVED" if (h % 10_000) / 10_000.0 >= rate
                       else "REJECTED", "mode": "blind"}
        eq, _, info = execute(stream, fake, "blind", closes, opens, cal, 100_000.0,
                              "passthrough")
        sharpes.append(metric_suite(eq.dropna(), rf)["sharpe"])
        fills.append(info["fills"])
    arr = np.array(sharpes)
    beat = int((m_b["sharpe"] > arr).sum())

    print("=== Gate experiment, realized risk-free rate ===")
    print(f"{'':16s} {'Sharpe':>7s} {'Sortino':>8s} {'CAGR%':>7s} {'maxDD%':>7s} "
          f"{'fills':>6s} {'turn':>6s}")
    for name, m, info in (("A (no gate)", m_a, info_a), ("B (gate on)", m_b, info_b)):
        print(f"{name:16s} {m['sharpe']:>7.2f} {m['sortino']:>8.2f} "
              f"{m['cagr_pct']:>7.1f} {m['max_dd_pct']:>7.1f} "
              f"{info['fills']:>6d} {info['turnover']:>6.2f}")
    print(f"{'C (random)':16s} {arr.mean():>7.2f} {'--':>8s} {'--':>7s} {'--':>7s} "
          f"{np.mean(fills):>6.0f} {'--':>6s}")
    print(f"  arm C spread: {arr.mean():.2f} +/- {arr.std():.2f} "
          f"[p5 {np.percentile(arr,5):.2f}, p95 {np.percentile(arr,95):.2f}]")
    print(f"  arm B beats {beat}/25 random gates, empirical p = {1 - beat/25:.2f}")
    print(f"  rejection rate {rate:.1%}")

    # --- Deflated Sharpe on the same footing -------------------------------
    curves = pd.read_pickle(PAPER_DIR / "equity_curves.pkl")
    var_period = float(np.var(OBSERVED_TRIAL_SHARPES, ddof=1)) / TRADING_DAYS
    print("\n=== Deflated Sharpe, realized risk-free rate ===")
    dsr_rows = {}
    for wname, label in (("selection", "Selection 2018-2024"),
                         ("holdout", "Holdout 2008-2017")):
        eq = curves[f"{wname}/mix"]
        spy = curves[f"{wname}/SPY"]
        ex = _excess_returns(eq, rf)
        sr = metric_suite(eq, rf)["sharpe"]
        spy_sr = metric_suite(spy, rf)["sharpe"]
        psr0 = probabilistic_sharpe_ratio(ex, 0.0)
        psrb = probabilistic_sharpe_ratio(ex, spy_sr)
        dsr = deflated_sharpe_ratio(ex, n_trials=len(OBSERVED_TRIAL_SHARPES),
                                    sr_variance_across_trials=var_period)
        dsr_rows[label] = {"days": len(ex), "sr": sr, "spy_sr": spy_sr,
                           "psr0": psr0, "psr_bench": psrb, "dsr": dsr}
        print(f"{label:22s} days {len(ex):>5d}  SR {sr:>5.2f}  "
              f"PSR>0 {psr0:>6.3f}  PSR>SPY {psrb:>6.3f}  DSR {dsr:>6.3f}")

    out = PAPER_DIR / "gate_results_realized.json"
    out.write_text(json.dumps({
        "arm_a": m_a, "arm_b": m_b,
        "arm_a_fills": info_a["fills"], "arm_b_fills": info_b["fills"],
        "arm_a_turnover": info_a["turnover"], "arm_b_turnover": info_b["turnover"],
        "arm_c": {"sharpe_mean": float(arr.mean()), "sharpe_std": float(arr.std()),
                  "p5": float(np.percentile(arr, 5)), "p95": float(np.percentile(arr, 95)),
                  "fills_mean": float(np.mean(fills)), "beat": beat, "trials": 25,
                  "p_empirical": 1 - beat / 25},
        "reject_rate": rate, "deflated": dsr_rows,
    }, indent=1, default=float), encoding="utf-8")
    print(f"\nWrote {out}")


def _selfcheck() -> None:
    """Check the excess-return conversion against a hand-computable case."""
    idx = pd.date_range("2020-01-01", periods=TRADING_DAYS + 1, freq="B")
    eq = pd.Series(100_000 * np.cumprod(np.full(len(idx), 1.0004)), index=idx)
    # With a zero rate, excess returns equal raw returns exactly.
    zero = pd.Series(0.0, index=idx)
    ex = _excess_returns(eq, zero)
    assert np.allclose(ex, eq.pct_change().dropna().to_numpy()), ex[:3]
    # With a positive rate, every excess return must be strictly smaller.
    pos = _excess_returns(eq, pd.Series(0.05, index=idx))
    assert (pos < ex).all(), (pos[:3], ex[:3])
    # And the shortfall is the daily equivalent of the annual rate.
    assert abs((ex - pos).mean() - ((1.05) ** (1 / TRADING_DAYS) - 1)) < 1e-12
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 22A95EF4CB87 - verify with scripts/authorship.py verify
