# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-A489ECE60C3E
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""DualMomentumSleeve: Antonacci GEM over asset-class ETFs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.front_office.strategy.sleeves.dual_momentum import DualMomentumSleeve

_FULL = {
    "SPY.NYSE": (100.0, 150.0),   # +50% — strongest risk asset
    "EFA.NYSE": (100.0, 110.0),
    "TLT.NASDAQ": (100.0, 105.0),
    "GLD.NYSE": (100.0, 108.0),
    "DBC.NYSE": (100.0, 90.0),
    "BIL.NYSE": (100.0, 102.0),
}


def _bars(trends: dict[str, tuple[float, float]], n: int = 300):
    idx = pd.bdate_range("2019-01-01", periods=n)
    out = {}
    for sym, (start, end) in trends.items():
        close = pd.Series(np.linspace(start, end, n), index=idx)
        out[sym] = pd.DataFrame(
            {"open": close, "high": close, "low": close, "close": close, "volume": 1e6},
            index=idx,
        )
    return out, idx[-1]


def test_gem_picks_strongest_risk_asset():
    bars, as_of = _bars(_FULL)
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["SPY.NYSE"] == 1.0
    assert all(v == 0.0 for k, v in w.items() if k != "SPY.NYSE")


def test_gem_falls_to_tlt_when_cash_beats_all():
    bars, as_of = _bars({
        "SPY.NYSE": (100.0, 95.0),
        "EFA.NYSE": (100.0, 96.0),
        "TLT.NASDAQ": (100.0, 99.0),
        "GLD.NYSE": (100.0, 97.0),
        "DBC.NYSE": (100.0, 90.0),
        "BIL.NYSE": (100.0, 104.0),   # cash wins -> defensive TLT
    })
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["TLT.NASDAQ"] == 1.0
    assert all(v == 0.0 for k, v in w.items() if k != "TLT.NASDAQ")


def test_gem_graceful_when_insufficient_history():
    bars, as_of = _bars({"SPY.NYSE": (100.0, 150.0)}, n=100)  # < 253 rows
    assert DualMomentumSleeve().compute(bars, as_of) == []


def test_gem_missing_cash_proxy_defaults_to_zero_threshold():
    trends = {k: v for k, v in _FULL.items() if k != "BIL.NYSE"}
    bars, as_of = _bars(trends)
    sigs = DualMomentumSleeve().compute(bars, as_of)
    w = {s.symbol: s.target_weight for s in sigs}
    assert w["SPY.NYSE"] == 1.0  # +50% > 0.0 threshold


def test_weights_sum_at_most_one_and_monthly_cadence():
    bars, as_of = _bars(_FULL)
    sleeve = DualMomentumSleeve()
    sigs = sleeve.compute(bars, as_of)
    assert sum(s.target_weight for s in sigs) <= 1.0 + 1e-9
    assert sleeve.rebalance_days == 21
    assert sleeve.name == "dual_momentum"
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token A489ECE60C3E - verify with scripts/authorship.py verify
