# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-23B2299D1421
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Portfolio risk overlay: vol targeting + 200d trend gate. Pure functions.

Parameters are LOCKED from published research and must not be tuned on any
test window afterward:
  - 15% vol target, 20d realized window: Moreira-Muir (2017), "Volatility-
    Managed Portfolios".
  - 200d SMA trend gate on the market index: Faber (2007), "A Quantitative
    Approach to Tactical Asset Allocation".

The overlay can only DE-RISK (scalar in [0, 1], never levers up). Every
degenerate input (short history, NaNs, missing symbols) fails OPEN to 1.0 —
i.e., falls back to current behavior, never crashes, never zeroes exposure
by accident.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
VOL_TARGET = 0.15
VOL_WINDOW = 20
SMA_WINDOW = 200


def vol_target_scalar(
    returns: pd.Series, target: float = VOL_TARGET, window: int = VOL_WINDOW
) -> float:
    """min(1, target/realized) from the trailing ``window`` of daily returns."""
    r = returns.dropna()
    if len(r) < window:
        return 1.0
    vol = float(r.iloc[-window:].std() * np.sqrt(TRADING_DAYS))
    if not np.isfinite(vol) or vol <= 0.0:
        return 1.0
    return min(1.0, target / vol)


def trend_gate(index_close: pd.Series, sma_window: int = SMA_WINDOW) -> float:
    """1.0 when the index is at/above its SMA, else 0.0. Fail-open on short data."""
    c = index_close.dropna()
    if len(c) < sma_window:
        return 1.0
    return 1.0 if float(c.iloc[-1]) >= float(c.iloc[-sma_window:].mean()) else 0.0


def portfolio_returns(closes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Daily returns of the weight-normalized basket (only symbols present)."""
    cols = [s for s in weights if s in closes.columns]
    if not cols:
        return pd.Series(dtype=float)
    w = pd.Series({s: weights[s] for s in cols})
    total = float(w.abs().sum())
    if total <= 0.0:
        return pd.Series(dtype=float)
    return (closes[cols].pct_change() * (w / total)).sum(axis=1)


def overlay_scalar(
    closes: pd.DataFrame,
    weights: dict[str, float],
    index_close: pd.Series,
    target: float = VOL_TARGET,
) -> float:
    """Combined exposure multiplier in [0, 1]: vol targeting x trend gate."""
    return vol_target_scalar(portfolio_returns(closes, weights), target) * trend_gate(index_close)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 23B2299D1421 - verify with scripts/authorship.py verify
