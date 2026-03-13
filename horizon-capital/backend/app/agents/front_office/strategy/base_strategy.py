"""Abstract base class for all trading strategies."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    """Lightweight signal DTO emitted by strategies before DB persistence.

    Attributes
    ----------
    symbol : str
        Instrument identifier (e.g. ``"RELIANCE.NSE"``).
    direction : int
        ``+1`` for BUY, ``-1`` for SELL, ``0`` for NEUTRAL / close.
    strength : float
        Confidence / conviction in ``[0.0, 1.0]``.
    strategy_name : str
        Originating strategy.
    regime : str
        Regime active when the signal was generated.
    reasoning : str
        Human-readable explanation.
    meta : dict
        Arbitrary metadata (indicator values, thresholds, etc.).
    target_price : float | None
        Optional target price.
    stop_loss : float | None
        Optional stop-loss level.
    """

    symbol: str
    direction: int  # +1 BUY, -1 SELL, 0 NEUTRAL
    strength: float
    strategy_name: str
    regime: str
    reasoning: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    target_price: float | None = None
    stop_loss: float | None = None


class BaseStrategy(abc.ABC):
    """Every concrete strategy must implement ``generate_signal`` and declare
    which regimes it is active in."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short, unique name of the strategy (e.g. ``'momentum'``)."""
        ...

    @property
    @abc.abstractmethod
    def active_regimes(self) -> list[str]:
        """List of regime names under which this strategy should run."""
        ...

    @abc.abstractmethod
    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        """Evaluate the current features and return a Signal (or ``None``).

        Parameters
        ----------
        symbol : str
            The instrument being evaluated.
        features : dict
            A dictionary of pre-computed technical indicators / features.
            Expected keys vary by strategy but typically include:
            ``rsi``, ``macd``, ``macd_signal``, ``ema_20``, ``close``,
            ``bb_upper``, ``bb_lower``, ``atr``, ``atr_avg_20``, ``vix_proxy``.
        regime : str
            The current market regime (``BULL``, ``BEAR``, ``HIGH_VOL``,
            ``CRISIS``, ``NEUTRAL``).

        Returns
        -------
        Signal | None
            A trading signal, or ``None`` if no actionable signal.
        """
        ...
