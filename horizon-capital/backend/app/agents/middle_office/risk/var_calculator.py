# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-8B18E5636F75
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Value-at-Risk and risk metric calculators.

Provides historical VaR, CVaR (Expected Shortfall), and drawdown computations
used by the RiskAgent and exposed for testing.
"""

from __future__ import annotations

import numpy as np


class VaRCalculator:
    """Static methods for VaR, CVaR, and drawdown calculations."""

    @staticmethod
    def compute_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Historical VaR at the given confidence level.

        Returns the potential loss at the given percentile (positive number).
        Returns 0.0 if the tail return is positive (no loss risk).
        """
        if len(returns) == 0:
            return 0.0
        percentile_value = float(np.percentile(returns, (1 - confidence) * 100))
        return max(-percentile_value, 0.0)

    @staticmethod
    def compute_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall)."""
        if len(returns) == 0:
            return 0.0
        cutoff = float(np.percentile(returns, (1 - confidence) * 100))
        tail = returns[returns <= cutoff]
        if len(tail) == 0:
            return 0.0
        return max(float(-np.mean(tail)), 0.0)

    @staticmethod
    def compute_max_drawdown(equity: np.ndarray) -> float:
        """Maximum peak-to-trough drawdown as a fraction.

        Parameters
        ----------
        equity:
            Equity curve (portfolio values over time).

        Returns
        -------
        float
            Maximum drawdown as a decimal (e.g. 0.2 = 20%).
        """
        if len(equity) < 2:
            return 0.0
        peak = equity[0]
        max_dd = 0.0
        for val in equity:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd
        return float(max_dd)

    @staticmethod
    def compute_current_drawdown(equity: np.ndarray) -> float:
        """Current drawdown from the all-time high.

        Parameters
        ----------
        equity:
            Equity curve.

        Returns
        -------
        float
            Current drawdown as a decimal.
        """
        if len(equity) < 2:
            return 0.0
        peak = float(np.max(equity))
        if peak == 0:
            return 0.0
        current = float(equity[-1])
        return max((peak - current) / peak, 0.0)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 8B18E5636F75 - verify with scripts/authorship.py verify
