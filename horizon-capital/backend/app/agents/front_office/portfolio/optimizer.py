"""Portfolio optimisation -- Kelly sizing, HRP weighting, Ledoit-Wolf covariance.

References
----------
- Lopez de Prado (2016), "Building Diversified Portfolios that Outperform
  Out of Sample", J. Portfolio Management (HRP).
- Ledoit & Wolf (2004), "Honey, I Shrunk the Sample Covariance Matrix",
  J. Portfolio Management (shrinkage estimator).
- MacLean, Thorp & Ziemba (2011), "The Kelly Capital Growth Investment
  Criterion", World Scientific (Half-Kelly).
"""

from __future__ import annotations

import numpy as np

from app.core.logging import get_logger

logger = get_logger("portfolio.optimizer")


class PortfolioOptimizer:
    """Position-sizing with HRP weighting and Ledoit-Wolf covariance."""

    # ------------------------------------------------------------------ #
    # Kelly criterion
    # ------------------------------------------------------------------ #

    @staticmethod
    def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
        """Full Kelly fraction.

        ``f* = (p * b - q) / b``  where p = win_rate, q = 1-p, b = win_loss_ratio.
        Clamped to [0, 1].
        """
        if win_loss_ratio <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0
        q = 1.0 - win_rate
        kelly = (win_rate * win_loss_ratio - q) / win_loss_ratio
        return max(0.0, min(kelly, 1.0))

    # ------------------------------------------------------------------ #
    # Position sizing (Half-Kelly, per MacLean, Thorp & Ziemba 2011)
    # ------------------------------------------------------------------ #

    @staticmethod
    def position_size(
        kelly_f: float,
        portfolio_value: float,
        price: float,
        max_pct: float = 0.05,
    ) -> float:
        """Number of shares (or units) to buy using Half-Kelly.

        Half-Kelly captures ~75% of full-Kelly growth with ~50% less drawdown.
        """
        if price <= 0 or portfolio_value <= 0:
            return 0.0
        half_kelly = kelly_f * 0.5
        allocation = portfolio_value * min(half_kelly, max_pct)
        shares = allocation / price
        return max(shares, 0.0)

    # ------------------------------------------------------------------ #
    # Ledoit-Wolf shrinkage covariance estimator
    # ------------------------------------------------------------------ #

    @staticmethod
    def ledoit_wolf_shrinkage(returns_matrix: np.ndarray) -> np.ndarray:
        """Ledoit-Wolf shrinkage estimator for the covariance matrix.

        Shrinks the sample covariance toward a structured target (scaled
        identity) to reduce estimation error.  The optimal shrinkage
        intensity is computed analytically (Ledoit & Wolf 2004, 3500 citations).

        Parameters
        ----------
        returns_matrix:
            Shape ``(T, N)`` -- T observations of N assets.

        Returns
        -------
        np.ndarray
            Shrunk covariance matrix of shape ``(N, N)``.
        """
        T, N = returns_matrix.shape  # noqa: N806
        if T < 2 or N < 1:
            return np.eye(max(N, 1))

        # Sample covariance
        X = returns_matrix - returns_matrix.mean(axis=0)  # noqa: N806
        sample_cov = (X.T @ X) / T

        # Shrinkage target: scaled identity (average variance)
        mu = np.trace(sample_cov) / N
        target = mu * np.eye(N)

        # Compute optimal shrinkage intensity
        delta = sample_cov - target
        # Sum of squared differences
        sum_sq = np.sum(delta ** 2)

        # Estimate numerator (sum of variances of covariance estimates)
        # Using the analytical formula from Ledoit & Wolf (2004)
        X2 = X ** 2  # noqa: N806
        # phi_hat: sum of element-wise variance of sample cov entries
        phi_hat = (1.0 / T**2) * (np.sum((X2.T @ X2) / T - sample_cov**2))

        # Clamp shrinkage intensity to [0, 1]
        if sum_sq == 0:
            shrinkage = 1.0
        else:
            shrinkage = max(0.0, min(phi_hat / sum_sq, 1.0))

        shrunk = shrinkage * target + (1 - shrinkage) * sample_cov

        logger.info(
            "ledoit_wolf_shrinkage",
            N=N,
            T=T,
            shrinkage_intensity=round(shrinkage, 4),
        )

        return shrunk

    # ------------------------------------------------------------------ #
    # Hierarchical Risk Parity (HRP) — Lopez de Prado (2016)
    # ------------------------------------------------------------------ #

    @staticmethod
    def hrp_weights(
        returns_matrix: np.ndarray,
        symbols: list[str],
    ) -> dict[str, float]:
        """Hierarchical Risk Parity portfolio weights.

        HRP uses hierarchical clustering on the correlation matrix to build
        a tree structure, then allocates risk by inverse-variance along the
        tree.  No matrix inversion required — avoids instability of
        Markowitz-style optimizers.

        Parameters
        ----------
        returns_matrix:
            Shape ``(T, N)`` — T observations of N assets.
        symbols:
            List of N symbol names corresponding to columns.

        Returns
        -------
        dict[str, float]
            Symbol -> weight mapping that sums to ~1.0.
        """
        N = returns_matrix.shape[1]  # noqa: N806
        if N == 0:
            return {}
        if N == 1:
            return {symbols[0]: 1.0}

        # Step 1: Compute shrunk covariance and correlation
        cov = PortfolioOptimizer.ledoit_wolf_shrinkage(returns_matrix)
        std = np.sqrt(np.diag(cov))
        std[std == 0] = 1e-8
        corr = cov / np.outer(std, std)
        np.fill_diagonal(corr, 1.0)
        corr = np.clip(corr, -1.0, 1.0)

        # Step 2: Distance matrix from correlation
        dist = np.sqrt(0.5 * (1 - corr))

        # Step 3: Hierarchical clustering (single-linkage)
        order = PortfolioOptimizer._quasi_diag(
            PortfolioOptimizer._tree_clustering(dist, N)
        )

        # Step 4: Recursive bisection for weights
        weights = PortfolioOptimizer._recursive_bisection(cov, order)

        return {symbols[i]: weights.get(i, 0.0) for i in range(N)}

    @staticmethod
    def _tree_clustering(dist: np.ndarray, n: int) -> list:
        """Single-linkage agglomerative clustering (no scipy dependency).

        Returns a linkage-like list of merges: [(i, j, dist), ...].
        """
        # Track which clusters are active
        active = set(range(n))
        {i: i for i in range(n)}
        next_id = n
        merges: list[tuple[int, int, float]] = []

        # Distance between clusters (initialize from dist matrix)
        cluster_dist: dict[tuple[int, int], float] = {}
        for i in range(n):
            for j in range(i + 1, n):
                cluster_dist[(i, j)] = dist[i, j]

        for _ in range(n - 1):
            # Find closest pair
            min_d = float("inf")
            best_pair = (0, 1)
            for (a, b), d in cluster_dist.items():
                if a in active and b in active and d < min_d:
                    min_d = d
                    best_pair = (a, b)

            a, b = best_pair
            merges.append((a, b, min_d))

            # Create new cluster
            new_id = next_id
            next_id += 1

            # Update distances (single-linkage = min)
            new_dists: dict[tuple[int, int], float] = {}
            for c in active:
                if c == a or c == b:
                    continue
                da = cluster_dist.get((min(a, c), max(a, c)), float("inf"))
                db = cluster_dist.get((min(b, c), max(b, c)), float("inf"))
                key = (min(new_id, c), max(new_id, c))
                new_dists[key] = min(da, db)

            # Remove old cluster entries
            active.discard(a)
            active.discard(b)
            active.add(new_id)

            # Update distance dict
            cluster_dist.update(new_dists)

        return merges

    @staticmethod
    def _quasi_diag(merges: list[tuple[int, int, float]]) -> list[int]:
        """Reorder assets by quasi-diagonalisation of the linkage.

        Recursively reorders leaves so that similar assets are adjacent.
        """
        if not merges:
            return [0]

        # Build tree from merges
        n = len(merges) + 1
        children: dict[int, tuple[int, int]] = {}
        next_id = n
        for a, b, _ in merges:
            children[next_id] = (a, b)
            next_id += 1

        root = next_id - 1

        # Traverse tree to get leaf order
        def _get_leaves(node: int) -> list[int]:
            if node < n:
                return [node]
            left, right = children[node]
            return _get_leaves(left) + _get_leaves(right)

        return _get_leaves(root)

    @staticmethod
    def _recursive_bisection(
        cov: np.ndarray,
        order: list[int],
    ) -> dict[int, float]:
        """Recursive bisection: allocate by inverse cluster variance."""
        weights: dict[int, float] = {i: 1.0 for i in order}

        cluster_items = [order]

        while cluster_items:
            next_level = []
            for cluster in cluster_items:
                if len(cluster) <= 1:
                    continue
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                # Cluster variance = w' * cov * w (inverse-variance weight)
                left_var = PortfolioOptimizer._cluster_var(cov, left)
                right_var = PortfolioOptimizer._cluster_var(cov, right)

                total_var = left_var + right_var
                if total_var == 0:
                    alpha = 0.5
                else:
                    alpha = 1 - left_var / total_var

                for i in left:
                    weights[i] *= alpha
                for i in right:
                    weights[i] *= (1 - alpha)

                next_level.append(left)
                next_level.append(right)

            cluster_items = next_level

        return weights

    @staticmethod
    def _cluster_var(cov: np.ndarray, indices: list[int]) -> float:
        """Variance of an equal-weight sub-portfolio."""
        sub_cov = cov[np.ix_(indices, indices)]
        n = len(indices)
        w = np.ones(n) / n
        return float(w @ sub_cov @ w)

    # ------------------------------------------------------------------ #
    # Correlation penalty (legacy — used when HRP is not applicable)
    # ------------------------------------------------------------------ #

    @staticmethod
    def correlation_penalty(
        symbol: str,
        positions: list[str],
        correlation_matrix: np.ndarray,
        symbols_index: list[str] | None = None,
    ) -> float:
        """Reduce position size when highly correlated with existing holdings."""
        if len(positions) == 0 or correlation_matrix.size == 0:
            return 1.0

        index = symbols_index if symbols_index is not None else positions
        if symbol not in index:
            return 1.0

        sym_idx = index.index(symbol)

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
        if avg_corr <= 0.5:
            return 1.0
        penalty = 1.0 - 1.5 * (avg_corr - 0.5)
        return max(penalty, 0.25)
