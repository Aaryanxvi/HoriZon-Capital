"""Abstract base class for all trading strategies."""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger("strategy.base")


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
    llm_enhanced : bool
        Whether an LLM was used to generate/enhance this signal.
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
    llm_enhanced: bool = False


class BaseStrategy(abc.ABC):
    """Every concrete strategy must implement ``generate_signal`` and declare
    which regimes it is active in.

    Supports an optional LLM reasoning path: if ``llm_provider`` is set,
    the strategy will attempt to use the LLM for enhanced signal analysis,
    falling back to rule-based logic when no LLM is available.
    """

    def __init__(self, llm_provider: str = "") -> None:
        self._llm_provider = llm_provider

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

    @property
    def llm_system_prompt(self) -> str:
        """Override in subclasses to provide a strategy-specific LLM persona."""
        return (
            "You are a quantitative trading strategist. Analyze the given "
            "technical indicators and market context. Return a JSON object with: "
            '{"direction": 1|-1|0, "strength": 0.0-1.0, "reasoning": "..."}'
        )

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

    async def generate_signal_with_llm(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        """Try LLM-enhanced signal generation, fall back to rule-based.

        Call this instead of ``generate_signal`` when you want to leverage
        the LLM if available.
        """
        if not self._llm_provider:
            return self.generate_signal(symbol, features, regime)

        try:
            from app.llm.provider_registry import provider_registry
            provider = provider_registry.get_provider(self._llm_provider)
            if provider is None:
                return self.generate_signal(symbol, features, regime)

            # Build feature summary for the LLM
            feature_lines = [f"- {k}: {v}" for k, v in features.items() if v is not None]
            user_prompt = (
                f"## Symbol: {symbol}\n"
                f"## Regime: {regime}\n"
                f"## Strategy: {self.name}\n"
                f"## Technical Indicators:\n" + "\n".join(feature_lines) + "\n\n"
                "Analyze these indicators from your specialist perspective. "
                "Should we BUY (direction=1), SELL (direction=-1), or HOLD (direction=0)?\n"
                "Return ONLY a JSON object: "
                '{"direction": <int>, "strength": <float 0-1>, "reasoning": "<string>"}'
            )

            response = await provider.complete(
                system_prompt=self.llm_system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
            )

            # Parse LLM response
            parsed = self._parse_llm_response(response)
            if parsed is None:
                logger.warning("llm_parse_failed", strategy=self.name, symbol=symbol)
                return self.generate_signal(symbol, features, regime)

            direction = int(parsed.get("direction", 0))
            strength = float(parsed.get("strength", 0.0))
            reasoning = str(parsed.get("reasoning", ""))

            if direction == 0 or strength < 0.1:
                return None

            return Signal(
                symbol=symbol,
                direction=max(-1, min(1, direction)),
                strength=max(0.0, min(1.0, strength)),
                strategy_name=self.name,
                regime=regime,
                reasoning=f"[LLM] {reasoning}",
                meta=dict(features),
                llm_enhanced=True,
            )

        except Exception as exc:
            logger.warning(
                "llm_strategy_fallback",
                strategy=self.name,
                symbol=symbol,
                error=str(exc),
            )
            return self.generate_signal(symbol, features, regime)

    @staticmethod
    def _parse_llm_response(response: str) -> dict | None:
        """Extract JSON from an LLM response string."""
        # Try direct JSON parse
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try extracting JSON from markdown code block
        if "```" in response:
            for block in response.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except (json.JSONDecodeError, TypeError):
                    continue
        # Try finding JSON object in the text
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(response[start:end])
            except (json.JSONDecodeError, TypeError):
                pass
        return None
