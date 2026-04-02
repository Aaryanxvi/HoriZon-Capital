"""Strategy agent -- runs the ensemble selector on a timer to produce signals.

Polls features from the FeatureStore every 60 seconds, fetches the current
regime from the regime_states table, and runs ``EnsembleSelector.generate_signals()``
for each symbol.  Emits signals on ``horizon.signal.{symbol}`` and persists
them to the ``signals`` table.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.strategy.ensemble_selector import EnsembleSelector
from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger("strategy.agent")

POLL_INTERVAL = 60  # seconds


class StrategyAgent(BaseAgent):
    """Periodically generates trading signals for all configured symbols."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="strategy-agent-1",
            agent_type="strategy",
            bus=bus,
            department="front_office",
        )
        from app.llm.provider_registry import provider_registry
        _provider = provider_registry.get_provider_name_for_department("front_office")
        self._ensemble = EnsembleSelector(llm_provider=_provider)
        self._symbols = self._load_symbols()

    @staticmethod
    def _load_symbols() -> list[str]:
        """Parse all symbols from settings."""
        symbols: list[str] = []
        for csv in [settings.india_symbols, settings.us_symbols, settings.crypto_symbols]:
            symbols.extend(s.strip() for s in csv.split(",") if s.strip())
        return symbols

    # ------------------------------------------------------------------
    # BaseAgent hooks
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.features.*", self.on_message)
        await self.bus.subscribe("horizon.regime.update", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        """Log incoming events; the main loop drives signal generation."""
        if message.message_type == MessageType.REGIME_UPDATE:
            payload = message.payload
            scope = payload.get("market_scope", "")
            regime = payload.get("regime", "")
            logger.info("regime_received", scope=scope, regime=regime)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        # Wait for data ingestion + features to warm up
        await asyncio.sleep(15)
        logger.info("strategy_agent_starting", symbols=self._symbols)

        while self._running:
            for symbol in self._symbols:
                try:
                    await self._generate_for_symbol(symbol)
                except Exception as exc:
                    logger.error("strategy_error", symbol=symbol, error=str(exc))
            await asyncio.sleep(POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Per-symbol signal generation
    # ------------------------------------------------------------------

    async def _generate_for_symbol(self, symbol: str) -> None:
        """Load features + regime, run ensemble, emit & persist signals."""
        # Load features from KV cache
        features_raw = await self._get_features(symbol)
        if not features_raw:
            return

        # Convert string values to floats
        features: dict[str, float] = {}
        for k, v in features_raw.items():
            if k in ("timestamp", "symbol", "timeframe"):
                continue
            try:
                features[k] = float(v)
            except (ValueError, TypeError):
                continue

        if not features:
            return

        # Get current regime
        regime = await self._get_regime(symbol)

        # Run ensemble: LLM-enhanced if provider available, else rule-based
        if self._ensemble._llm_provider:
            signals = await self._ensemble.generate_signals_async(
                symbol, features, regime
            )
        else:
            signals = self._ensemble.generate_signals(symbol, features, regime)

        for sig in signals:
            # Emit on bus
            payload = {
                "symbol": sig.symbol,
                "direction": sig.direction,
                "strength": sig.strength,
                "strategy_name": sig.strategy_name,
                "regime": sig.regime,
                "reasoning": sig.reasoning,
                "target_price": sig.target_price,
                "stop_loss": sig.stop_loss,
                "llm_enhanced": sig.llm_enhanced,
                "meta": sig.meta,
            }
            await self.emit(
                channel=f"horizon.signal.{symbol}",
                message_type=MessageType.SIGNAL,
                payload=payload,
            )

            # Persist to signals table
            await self._persist_signal(sig, payload)

            logger.info(
                "signal_emitted",
                symbol=sig.symbol,
                direction=sig.direction,
                strength=sig.strength,
                strategy=sig.strategy_name,
            )

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_features(symbol: str, timeframe: str = "1d") -> dict[str, str] | None:
        """Read latest features from KV cache.

        The feature computation worker stores features keyed by the raw symbol
        (without exchange suffix), e.g. ``RELIANCE`` not ``RELIANCE.NSE``.
        """
        raw = symbol.split(".")[0] if "." in symbol else symbol
        redis_key = f"horizon:features:{raw}:{timeframe}"
        data = await get_kv_store().hgetall(redis_key)
        return data if data else None

    @staticmethod
    async def _get_regime(symbol: str) -> str:
        """Determine current regime from the regime_states table.

        Maps the symbol to a market scope and reads the most recent regime.
        """
        # Map symbol to scope
        scope = "US"
        upper = symbol.upper()
        if upper.endswith(".NSE") or upper.endswith(".BSE"):
            scope = "INDIA"
        elif "BTC" in upper or "ETH" in upper or "-USD" in upper:
            scope = "CRYPTO"

        try:
            async with _get_session_factory()() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT regime FROM regime_states
                        WHERE market_scope = :scope
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"scope": scope},
                )
                row = result.scalar_one_or_none()
                return row if row else "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    @staticmethod
    async def _persist_signal(sig, payload: dict) -> None:
        """Insert signal into the signals table."""
        try:
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO signals
                            (signal_id, agent_id, symbol, direction, strength,
                             confidence, strategy_name, regime, metadata, created_at)
                        VALUES
                            (:signal_id, :agent_id, :symbol, :direction, :strength,
                             :confidence, :strategy_name, :regime, :metadata, :now)
                        """
                    ),
                    {
                        "signal_id": str(uuid.uuid4()),
                        "agent_id": "strategy-agent-1",
                        "symbol": sig.symbol,
                        "direction": "BUY" if sig.direction > 0 else (
                            "SELL" if sig.direction < 0 else "HOLD"
                        ),
                        "strength": sig.strength,
                        "confidence": sig.strength,
                        "strategy_name": sig.strategy_name,
                        "regime": sig.regime,
                        "metadata": json.dumps(payload.get("meta", {}), default=str),
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("signal_persist_error", symbol=sig.symbol, error=str(exc))
