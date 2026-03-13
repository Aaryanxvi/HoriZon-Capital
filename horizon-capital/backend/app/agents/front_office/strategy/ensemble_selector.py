"""Ensemble selector -- dispatches signal generation to regime-appropriate strategies.

Holds all four strategies and, given the current regime, activates the subset
whose ``active_regimes`` list includes that regime.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal
from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy
from app.agents.front_office.strategy.mean_reversion_strategy import MeanReversionStrategy
from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy
from app.agents.front_office.strategy.volatility_strategy import VolatilityStrategy
from app.core.logging import get_logger

logger = get_logger("strategy.ensemble")


class EnsembleSelector:
    """Routes signal generation through the appropriate strategies for the
    current market regime."""

    def __init__(self) -> None:
        self._strategies: list[BaseStrategy] = [
            MomentumStrategy(),
            MeanReversionStrategy(),
            VolatilityStrategy(),
            CrisisStrategy(),
        ]

    @property
    def strategies(self) -> list[BaseStrategy]:
        return list(self._strategies)

    def get_active_strategies(self, regime: str) -> list[BaseStrategy]:
        """Return strategies whose ``active_regimes`` include *regime*."""
        active = [s for s in self._strategies if regime in s.active_regimes]
        if not active:
            logger.info(
                "no_active_strategies",
                regime=regime,
                available=[s.name for s in self._strategies],
            )
        return active

    def generate_signals(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> list[Signal]:
        """Run all active strategies for the given regime and collect their signals.

        Parameters
        ----------
        symbol : str
            The instrument being evaluated.
        features : dict
            Pre-computed technical indicators.
        regime : str
            Current market regime.

        Returns
        -------
        list[Signal]
            All non-None signals produced by the active strategies.
        """
        active = self.get_active_strategies(regime)
        signals: list[Signal] = []

        for strategy in active:
            try:
                sig = strategy.generate_signal(symbol, features, regime)
                if sig is not None:
                    signals.append(sig)
                    logger.info(
                        "signal_generated",
                        strategy=strategy.name,
                        symbol=symbol,
                        direction=sig.direction,
                        strength=sig.strength,
                    )
            except Exception as exc:
                logger.error(
                    "strategy_error",
                    strategy=strategy.name,
                    symbol=symbol,
                    error=str(exc),
                )

        logger.info(
            "ensemble_result",
            regime=regime,
            symbol=symbol,
            n_active=len(active),
            n_signals=len(signals),
        )
        return signals
