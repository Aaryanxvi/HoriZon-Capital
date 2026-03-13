"""Portfolio optimisation helpers -- Kelly sizing and correlation penalties."""

import numpy as np


class PortfolioOptimizer:
    """Stateless position-sizing utilities.

    Implements the Kelly criterion for edge-based sizing and a simple
    correlation penalty to reduce concentration risk.
    """

    # ------------------------------------------------------------------ #
    # Kelly criterion
    # ------------------------------------------------------------------ #

    @staticmethod
    def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
        """Full Kelly fraction.

        Parameters
        ----------
        win_rate:
            Probability of a winning trade (0-1).
        win_loss_ratio:
            Average-win / average-loss (positive number).

        Returns
        -------
        float
            Kelly fraction in [0, 1].  Returns 0 if the edge is negative.

        Notes
        -----
        ``f* = (p * b - q) / b``  where  p = win_rate, q = 1-p, b = win_loss_ratio.
        We clamp to [0, 1] and typically use a *half-Kelly* in practice.
        """
        if win_loss_ratio <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0
        q = 1.0 - win_rate
        kelly = (win_rate * win_loss_ratio - q) / win_loss_ratio
        return max(0.0, min(kelly, 1.0))

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    @staticmethod
    def position_size(
        kelly_f: float,
        portfolio_value: float,
        price: float,
        max_pct: float = 0.05,
    ) -> float:
        """Number of shares (or units) to buy.

        Parameters
        ----------
        kelly_f:
            Kelly fraction (often halved for safety).
        portfolio_value:
            Total portfolio NAV.
        price:
            Current price of the asset.
        max_pct:
            Hard cap as a fraction of portfolio value (default 5 %).

        Returns
        -------
        float
            Number of shares.  May be fractional for crypto; round down
            for equities externally.
        """
        if price <= 0 or portfolio_value <= 0:
            return 0.0

        # Use half-Kelly for safety
        half_kelly = kelly_f * 0.5

        # Dollar amount to allocate
        allocation = portfolio_value * min(half_kelly, max_pct)

        shares = allocation / price
        return max(shares, 0.0)

    # ------------------------------------------------------------------ #
    # Correlation penalty
    # ------------------------------------------------------------------ #

    @staticmethod
    def correlation_penalty(
        symbol: str,
        positions: list[str],
        correlation_matrix: np.ndarray,
        symbols_index: list[str] | None = None,
    ) -> float:
        """Reduce position size when highly correlated with existing holdings.

        Parameters
        ----------
        symbol:
            The candidate symbol to add.
        positions:
            List of symbols currently held.
        correlation_matrix:
            Square correlation matrix (n x n).
        symbols_index:
            Ordered list of symbol names corresponding to matrix rows/cols.
            If ``None``, falls back to ``positions`` ordering (length must
            match the matrix dimension).

        Returns
        -------
        float
            Multiplier in (0, 1].  1.0 means no penalty; lower values
            reduce the position size proportionally.
        """
        if len(positions) == 0 or correlation_matrix.size == 0:
            return 1.0

        index = symbols_index if symbols_index is not None else positions
        if symbol not in index:
            return 1.0

        sym_idx = index.index(symbol)

        # Average absolute correlation with existing positions
        correlations: list[float] = []
        for pos_symbol in positions:
            if pos_symbol == symbol:
                continue
            if pos_symbol not in index:
                continue
            pos_idx = index.index(pos_symbol)
            if sym_idx < correlation_matrix.shape[0] and pos_idx < correlation_matrix.shape[1]:
                correlations.append(abs(float(correlation_matrix[sym_idx, pos_idx])))

        if not correlations:
            return 1.0

        avg_corr = float(np.mean(correlations))

        # Penalty: linearly scale down for avg correlation > 0.5
        # At avg_corr = 0.5 -> multiplier = 1.0
        # At avg_corr = 1.0 -> multiplier = 0.25
        if avg_corr <= 0.5:
            return 1.0
        penalty = 1.0 - 1.5 * (avg_corr - 0.5)  # goes from 1.0 to 0.25
        return max(penalty, 0.25)
