"""Value-at-Risk and drawdown calculations using historical simulation."""

import numpy as np


class VaRCalculator:
    """Simple historical-simulation VaR calculator.

    All methods are pure functions operating on numpy arrays so that the
    calculator stays stateless and easy to test.
    """

    # ------------------------------------------------------------------ #
    # Value at Risk
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Historical VaR at the given confidence level.

        Parameters
        ----------
        returns:
            Array of daily (or intraday) returns.  A 252-element window is
            recommended for a 1-year lookback, but any length is accepted.
        confidence:
            Confidence level, e.g. 0.95 for 95 % VaR.

        Returns
        -------
        float
            The *positive* VaR value representing the maximum expected loss
            at the specified confidence level.  For example, 0.02 means the
            portfolio is unlikely to lose more than 2 % in a single day
            with ``(1 - confidence)`` probability.
        """
        if len(returns) == 0:
            return 0.0
        # Take the worst returns at the (1-confidence) quantile
        percentile = (1 - confidence) * 100
        var_value = float(np.percentile(returns, percentile))
        # Return as a positive number (loss magnitude)
        return abs(var_value)

    # ------------------------------------------------------------------ #
    # Conditional VaR (Expected Shortfall)
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Conditional VaR (Expected Shortfall) -- the mean of losses
        exceeding the VaR threshold.

        Parameters
        ----------
        returns:
            Array of daily returns.
        confidence:
            Confidence level.

        Returns
        -------
        float
            Positive number representing the average loss in the tail.
        """
        if len(returns) == 0:
            return 0.0
        percentile = (1 - confidence) * 100
        var_threshold = np.percentile(returns, percentile)
        tail_returns = returns[returns <= var_threshold]
        if len(tail_returns) == 0:
            return abs(float(var_threshold))
        return abs(float(np.mean(tail_returns)))

    # ------------------------------------------------------------------ #
    # Drawdown helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_max_drawdown(equity_curve: np.ndarray) -> float:
        """Maximum peak-to-trough drawdown as a positive fraction.

        Parameters
        ----------
        equity_curve:
            Array of cumulative portfolio values (e.g. NAV over time).

        Returns
        -------
        float
            Maximum drawdown as a decimal fraction (e.g. 0.12 = 12 %).
        """
        if len(equity_curve) < 2:
            return 0.0
        running_max = np.maximum.accumulate(equity_curve)
        drawdowns = (running_max - equity_curve) / np.where(running_max == 0, 1.0, running_max)
        return float(np.max(drawdowns))

    @staticmethod
    def compute_current_drawdown(equity_curve: np.ndarray) -> float:
        """Current drawdown from the last peak as a positive fraction.

        Parameters
        ----------
        equity_curve:
            Array of cumulative portfolio values.

        Returns
        -------
        float
            Current drawdown (0.0 if at or above the peak).
        """
        if len(equity_curve) < 2:
            return 0.0
        peak = float(np.max(equity_curve))
        if peak == 0:
            return 0.0
        current = float(equity_curve[-1])
        dd = (peak - current) / peak
        return max(dd, 0.0)
