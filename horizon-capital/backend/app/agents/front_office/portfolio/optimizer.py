"""Simple equal-weight portfolio allocation."""

from __future__ import annotations


class PortfolioOptimizer:
    """Allocates equal weight to each position."""

    @staticmethod
    def calculate_weights(symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        weight = 1.0 / len(symbols)
        return {s: weight for s in symbols}

    @staticmethod
    def position_size(
        portfolio_value: float,
        num_positions: int,
        max_pct: float = 0.05,
    ) -> float:
        if num_positions <= 0 or portfolio_value <= 0:
            return 0.0
        equal_share = portfolio_value / num_positions
        max_size = portfolio_value * max_pct
        return min(equal_share, max_size)
