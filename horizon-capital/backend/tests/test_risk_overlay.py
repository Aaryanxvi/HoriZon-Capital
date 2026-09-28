# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-CC822EF3D9B4
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Risk overlay: vol targeting + trend gate. All paths fail-open to 1.0."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.quant.risk_overlay import (
    overlay_scalar,
    portfolio_returns,
    trend_gate,
    vol_target_scalar,
)


def _series(vals: list[float]) -> pd.Series:
    return pd.Series(vals, index=pd.bdate_range("2020-01-01", periods=len(vals)))


def test_vol_scalar_caps_at_one_when_vol_below_target():
    r = _series([0.0001] * 60)  # near-zero vol
    assert vol_target_scalar(r) == 1.0


def test_vol_scalar_cuts_when_vol_high():
    rng = np.random.default_rng(0)
    r = _series(list(rng.normal(0.0, 0.03, 60)))  # ~48% annualized
    s = vol_target_scalar(r, target=0.15)
    assert 0.0 < s < 1.0


def test_vol_scalar_fail_open_on_short_or_empty_history():
    assert vol_target_scalar(_series([0.01] * 5)) == 1.0
    assert vol_target_scalar(pd.Series(dtype=float)) == 1.0


def test_trend_gate_flips_at_sma():
    up = _series(list(np.linspace(100.0, 200.0, 250)))
    down = _series(list(np.linspace(200.0, 100.0, 250)))
    assert trend_gate(up) == 1.0
    assert trend_gate(down) == 0.0


def test_trend_gate_fail_open_on_short_history():
    assert trend_gate(_series([100.0] * 50)) == 1.0


def test_portfolio_returns_weighting():
    idx = pd.bdate_range("2020-01-01", periods=3)
    closes = pd.DataFrame({"A": [100.0, 110.0, 121.0], "B": [100.0, 100.0, 100.0]}, index=idx)
    r = portfolio_returns(closes, {"A": 0.5, "B": 0.5})
    assert abs(r.iloc[-1] - 0.05) < 1e-9


def test_overlay_scalar_composes_and_bounds():
    idx = pd.bdate_range("2019-01-01", periods=300)
    closes = pd.DataFrame(
        {"A": np.linspace(50.0, 150.0, 300), "B": np.linspace(30.0, 90.0, 300)}, index=idx
    )
    weights = {"A": 0.5, "B": 0.5}
    spy_up = pd.Series(np.linspace(100.0, 200.0, 300), index=idx)
    spy_down = pd.Series(np.linspace(200.0, 100.0, 300), index=idx)
    s = overlay_scalar(closes, weights, spy_up)
    assert 0.0 <= s <= 1.0
    assert overlay_scalar(closes, weights, spy_down) == 0.0  # gate kills it


def test_overlay_scalar_fail_open_on_missing_symbols():
    idx = pd.bdate_range("2019-01-01", periods=300)
    closes = pd.DataFrame({"A": np.linspace(50.0, 150.0, 300)}, index=idx)
    spy_up = pd.Series(np.linspace(100.0, 200.0, 300), index=idx)
    # weights reference only symbols absent from closes -> no returns -> 1.0 * gate
    assert overlay_scalar(closes, {"ZZZ": 1.0}, spy_up) == 1.0
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token CC822EF3D9B4 - verify with scripts/authorship.py verify
