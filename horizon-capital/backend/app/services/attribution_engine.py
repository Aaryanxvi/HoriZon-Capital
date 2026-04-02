"""Per-trade attribution engine.

For each executed trade, computes and stores a breakdown of what contributed
to the decision:
  - Strategy alpha contribution (signal strength, strategy name)
  - Sentiment alpha contribution (sentiment score at trade time)
  - Regime influence (active regime, confidence)
  - Risk scaling adjustment (how risk limits modified position size)
  - Debate consensus details (votes, confidence scores)

Results stored in the ``trade_attributions`` table (created via local storage).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.messaging import AgentMessage

logger = get_logger("services.attribution")


class TradeAttribution:
    """Computed attribution breakdown for a single trade."""

    __slots__ = (
        "trade_id", "symbol", "side", "strategy_name", "strategy_alpha",
        "sentiment_alpha", "regime", "regime_confidence", "regime_influence",
        "risk_scaling", "debate_for", "debate_against", "debate_abstain",
        "debate_consensus_score", "timestamp",
    )

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s, None) for s in self.__slots__}


class AttributionEngine:
    """Listens for order fills and computes trade attribution.

    Caches recent signal, sentiment, regime, and debate data to attribute
    contributions when a fill arrives.
    """

    def __init__(self, bus) -> None:
        self.bus = bus
        self._recent_signals: dict[str, dict[str, Any]] = {}  # symbol -> signal payload
        self._recent_sentiment: dict[str, dict[str, Any]] = {}  # symbol -> sentiment
        self._recent_regimes: dict[str, dict[str, Any]] = {}  # scope -> regime data
        self._recent_debates: dict[str, dict[str, Any]] = {}  # symbol -> debate result
        self._attributions: list[dict[str, Any]] = []  # in-memory store
        self._active = False

    async def start(self) -> None:
        self._active = True
        await self.bus.subscribe("horizon.signal.*", self._on_signal)
        await self.bus.subscribe("horizon.features.*.sentiment", self._on_sentiment)
        await self.bus.subscribe("horizon.regime.update", self._on_regime)
        await self.bus.subscribe("horizon.debate.*.conclusion", self._on_debate)
        await self.bus.subscribe("horizon.execution.order.fill", self._on_fill)
        logger.info("attribution_engine_started")

    async def stop(self) -> None:
        self._active = False
        logger.info("attribution_engine_stopped")

    # ------------------------------------------------------------------
    # Event handlers — cache context data
    # ------------------------------------------------------------------

    async def _on_signal(self, message: AgentMessage) -> None:
        payload = message.payload
        symbol = payload.get("symbol", "")
        if symbol:
            self._recent_signals[symbol] = payload

    async def _on_sentiment(self, message: AgentMessage) -> None:
        payload = message.payload
        symbol = payload.get("symbol", "")
        if symbol:
            self._recent_sentiment[symbol] = payload

    async def _on_regime(self, message: AgentMessage) -> None:
        payload = message.payload
        scope = payload.get("market_scope", "")
        if scope:
            self._recent_regimes[scope] = payload

    async def _on_debate(self, message: AgentMessage) -> None:
        payload = message.payload
        symbol = payload.get("symbol", "")
        if symbol:
            self._recent_debates[symbol] = payload

    # ------------------------------------------------------------------
    # Attribution computation
    # ------------------------------------------------------------------

    async def _on_fill(self, message: AgentMessage) -> None:
        if not self._active:
            return

        payload = message.payload
        symbol = payload.get("symbol", "")
        trade_id = payload.get("order_id", payload.get("trade_id", ""))

        attribution = self._compute_attribution(trade_id, symbol, payload)
        self._attributions.append(attribution)

        # Keep only last 500
        if len(self._attributions) > 500:
            self._attributions = self._attributions[-500:]

        logger.info(
            "trade_attributed",
            trade_id=trade_id,
            symbol=symbol,
            strategy_alpha=attribution.get("strategy_alpha", 0),
        )

    def _compute_attribution(
        self, trade_id: str, symbol: str, fill_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute attribution breakdown for a filled trade."""
        now = datetime.now(UTC).isoformat()

        # Strategy alpha
        signal = self._recent_signals.get(symbol, {})
        strategy_name = signal.get("strategy_name", "unknown")
        strategy_alpha = signal.get("strength", 0.0)

        # Sentiment alpha
        sentiment = self._recent_sentiment.get(symbol, {})
        sentiment_alpha = sentiment.get("avg_sentiment", sentiment.get("sentiment_score", 0.0))

        # Regime influence
        # Determine scope from symbol
        scope = self._symbol_to_scope(symbol)
        regime_data = self._recent_regimes.get(scope, {})
        regime = regime_data.get("regime", "UNKNOWN")
        regime_confidence = regime_data.get("confidence", 0.0)

        # Regime influence: how well the regime aligns with the trade direction
        side = fill_payload.get("side", signal.get("direction", 0))
        regime_influence = self._compute_regime_influence(regime, side)

        # Risk scaling
        risk_scaling = fill_payload.get("risk_scaling", 1.0)

        # Debate consensus
        debate = self._recent_debates.get(symbol, {})
        debate_for = debate.get("for_count", 0)
        debate_against = debate.get("against_count", 0)
        debate_abstain = debate.get("abstain_count", 0)
        debate_consensus = debate.get("consensus_score", 0.0)

        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "side": side,
            "strategy_name": strategy_name,
            "strategy_alpha": round(float(strategy_alpha), 4),
            "sentiment_alpha": round(float(sentiment_alpha), 4),
            "regime": regime,
            "regime_confidence": round(float(regime_confidence), 4),
            "regime_influence": round(regime_influence, 4),
            "risk_scaling": round(float(risk_scaling), 4),
            "debate_for": debate_for,
            "debate_against": debate_against,
            "debate_abstain": debate_abstain,
            "debate_consensus_score": round(float(debate_consensus), 4),
            "timestamp": now,
        }

    @staticmethod
    def _symbol_to_scope(symbol: str) -> str:
        """Map a symbol to its market scope."""
        if symbol.endswith((".NSE", ".BSE")):
            return "INDIA"
        elif symbol.endswith((".NASDAQ", ".NYSE")):
            return "US"
        elif "-USD" in symbol:
            return "CRYPTO"
        return "US"

    @staticmethod
    def _compute_regime_influence(regime: str, side: Any) -> float:
        """Compute how much the regime helped/hurt the trade.

        Returns a value in [-1.0, 1.0]:
          positive = regime supports the trade direction
          negative = regime opposes the trade direction
        """
        try:
            direction = int(side)
        except (TypeError, ValueError):
            direction = 0

        regime_bias = {
            "BULL": 1.0,
            "BEAR": -1.0,
            "NEUTRAL": 0.0,
            "CRISIS": -0.8,
            "HIGH_VOL": -0.3,
            "HIGH_VOLATILITY": -0.3,
        }
        bias = regime_bias.get(regime, 0.0)
        if direction == 0:
            return 0.0
        # Positive influence = regime agrees with direction
        return round(bias * direction, 4)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_attributions(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent attributions, optionally filtered by symbol."""
        items = self._attributions
        if symbol:
            items = [a for a in items if a.get("symbol") == symbol]
        return list(reversed(items[-limit:]))
