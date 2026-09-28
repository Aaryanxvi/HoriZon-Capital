# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-E2DF2D807499
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Kelly criterion position sizing (Kelly 1956, Thorp 1969).

For continuous returns w/ normal-ish distribution:
    f* = mu / sigma^2   (full Kelly)
    f_half = 0.5 * f*   (half-Kelly, Thorp-recommended for safety)

Half-Kelly trades ~3/4 of full-Kelly's geometric growth for ~1/2 the variance.
Caps at MAX_LEVERAGE to prevent blowup on regime shifts.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def full_kelly_fraction(returns: Sequence[float]) -> float:
    """f* = mean / variance using historical returns."""
    r = np.asarray(returns, dtype=float)
    if r.size < 30:
        return 0.0
    mu = r.mean()
    var = r.var(ddof=1)
    if var <= 0:
        return 0.0
    return float(mu / var)


def half_kelly_fraction(returns: Sequence[float], cap: float = 2.0) -> float:
    """Half-Kelly with leverage cap. Returns fraction of NAV to allocate."""
    f = full_kelly_fraction(returns) * 0.5
    return float(max(0.0, min(f, cap)))


def kelly_size_per_asset(
    returns_df,  # pd.DataFrame T x N
    cap: float = 2.0,
    fractional: float = 0.5,
) -> dict[str, float]:
    """Compute per-asset Kelly fractions. Negative => no allocation (long-only)."""
    out: dict[str, float] = {}
    for col in returns_df.columns:
        f = full_kelly_fraction(returns_df[col].dropna()) * fractional
        out[col] = float(max(0.0, min(f, cap)))
    return out
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token E2DF2D807499 - verify with scripts/authorship.py verify
