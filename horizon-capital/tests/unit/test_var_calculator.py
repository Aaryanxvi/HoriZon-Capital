# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-4C4F68C907F2
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Unit tests for VaRCalculator."""

import numpy as np
import pytest

from app.agents.middle_office.risk.var_calculator import VaRCalculator


class TestVaR95:
    """Tests for 95% Value-at-Risk."""

    def test_var_95_known_distribution(self) -> None:
        """VaR at 95% on a standard normal sample should be ~1.645 std devs."""
        np.random.seed(42)
        returns = np.random.normal(0, 0.02, 10_000)
        var = VaRCalculator.compute_var(returns, confidence=0.95)
        # 95th percentile of losses for ~N(0,0.02) should be around 0.033
        assert 0.025 < var < 0.045

    def test_var_95_all_positive(self) -> None:
        """When all returns are positive, VaR should be close to zero."""
        returns = np.abs(np.random.normal(0.01, 0.005, 1000))
        var = VaRCalculator.compute_var(returns, confidence=0.95)
        # 5th percentile of all-positive returns is still positive
        assert var >= 0.0

    def test_var_95_empty(self) -> None:
        """Empty returns array should return 0."""
        var = VaRCalculator.compute_var(np.array([]), confidence=0.95)
        assert var == 0.0

    def test_var_95_single_value(self) -> None:
        """Single return value should return its absolute value."""
        var = VaRCalculator.compute_var(np.array([-0.05]), confidence=0.95)
        assert var == pytest.approx(0.05, abs=0.001)


class TestVaR99:
    """Tests for 99% Value-at-Risk."""

    def test_var_99_greater_than_95(self) -> None:
        """99% VaR should always be >= 95% VaR."""
        np.random.seed(42)
        returns = np.random.normal(0, 0.02, 5000)
        var_95 = VaRCalculator.compute_var(returns, confidence=0.95)
        var_99 = VaRCalculator.compute_var(returns, confidence=0.99)
        assert var_99 >= var_95

    def test_var_99_known_distribution(self) -> None:
        """VaR at 99% on normal returns should be roughly 2.33 std devs."""
        np.random.seed(42)
        returns = np.random.normal(0, 0.02, 10_000)
        var = VaRCalculator.compute_var(returns, confidence=0.99)
        # Expected: ~0.046
        assert 0.035 < var < 0.060


class TestCVaR:
    """Tests for Conditional VaR (Expected Shortfall)."""

    def test_cvar_greater_than_var(self) -> None:
        """CVaR should be >= VaR since it averages the tail."""
        np.random.seed(42)
        returns = np.random.normal(-0.001, 0.02, 5000)
        var = VaRCalculator.compute_var(returns, confidence=0.95)
        cvar = VaRCalculator.compute_cvar(returns, confidence=0.95)
        assert cvar >= var

    def test_cvar_empty(self) -> None:
        """Empty returns should give CVaR of 0."""
        cvar = VaRCalculator.compute_cvar(np.array([]), confidence=0.95)
        assert cvar == 0.0

    def test_cvar_all_same(self) -> None:
        """Constant returns should give CVaR equal to the absolute value."""
        returns = np.full(100, -0.01)
        cvar = VaRCalculator.compute_cvar(returns, confidence=0.95)
        assert cvar == pytest.approx(0.01, abs=0.001)


class TestMaxDrawdown:
    """Tests for maximum drawdown computation."""

    def test_max_drawdown_monotonic_up(self) -> None:
        """A monotonically increasing equity curve has zero drawdown."""
        equity = np.array([100, 110, 120, 130, 140, 150])
        dd = VaRCalculator.compute_max_drawdown(equity)
        assert dd == 0.0

    def test_max_drawdown_known(self) -> None:
        """Known equity curve with a 20% drawdown."""
        equity = np.array([100, 120, 96, 110, 130])
        # Peak 120, trough 96 => drawdown = 24/120 = 0.2
        dd = VaRCalculator.compute_max_drawdown(equity)
        assert dd == pytest.approx(0.2, abs=0.001)

    def test_max_drawdown_single_point(self) -> None:
        """Fewer than 2 points should return 0."""
        dd = VaRCalculator.compute_max_drawdown(np.array([100]))
        assert dd == 0.0

    def test_max_drawdown_with_recovery(self) -> None:
        """Drawdown should measure peak-to-trough even after recovery."""
        equity = np.array([100, 150, 75, 200])
        # Peak 150, trough 75 => 50%
        dd = VaRCalculator.compute_max_drawdown(equity)
        assert dd == pytest.approx(0.5, abs=0.001)

    def test_current_drawdown(self) -> None:
        """Current drawdown when the last value is below the peak."""
        equity = np.array([100, 200, 180])
        dd = VaRCalculator.compute_current_drawdown(equity)
        # Peak 200, current 180 => 10%
        assert dd == pytest.approx(0.1, abs=0.001)

    def test_current_drawdown_at_peak(self) -> None:
        """Current drawdown is zero when at the all-time high."""
        equity = np.array([100, 150, 200])
        dd = VaRCalculator.compute_current_drawdown(equity)
        assert dd == 0.0
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 4C4F68C907F2 - verify with scripts/authorship.py verify
