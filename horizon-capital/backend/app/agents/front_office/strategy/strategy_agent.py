"""Strategy agent -- runs the three basic strategies on a timer to produce signals.

Polls OHLCV data from the KV cache every 60 seconds and runs RSIStrategy,
MACDStrategy, and BollingerBandStrategy for each symbol. Emits signals on
``horizon.signal.{symbol}`` and persists them to the ``signals`` table.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.strategy.simple_strategies import (
    BollingerBandStrategy,
    MACDStrategy,
    RSIStrategy,
)
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
        self._strategies = [RSIStrategy(), MACDStrategy(), BollingerBandStrategy()]
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

    async def on_message(self, message: AgentMessage) -> None:
        """Log incoming feature updates."""
        if message.message_type == MessageType.FEATURE_UPDATE:
            logger.debug("feature_update_received", channel=message.channel)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
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
        """Load OHLCV data, run each strategy, emit & persist signals."""
        df = await self._get_ohlcv(symbol)
        if df is None or df.empty:
            return

        for strategy in self._strategies:
            try:
                sig = strategy.generate_signal(symbol, df)
            except Exception as exc:
                logger.warning(
                    "strategy_run_error",
                    strategy=strategy.name,
                    symbol=symbol,
                    error=str(exc),
                )
                continue

            if sig is None:
                continue

            payload = {
                "symbol": sig.symbol,
                "direction": sig.direction,
                "strength": sig.strength,
                "strategy_name": sig.strategy_name,
                "reasoning": sig.reasoning,
                "target_price": sig.target_price,
                "stop_loss": sig.stop_loss,
            }
            await self.emit(
                channel=f"horizon.signal.{symbol}",
                message_type=MessageType.SIGNAL,
                payload=payload,
            )

            await self._persist_signal(sig)

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
    async def _get_ohlcv(symbol: str) -> pd.DataFrame | None:
        """Build a DataFrame from cached features stored by the feature worker."""
        raw = symbol.split(".")[0] if "." in symbol else symbol
        redis_key = f"horizon:features:{raw}:1d"
        data = await get_kv_store().hgetall(redis_key)
        if not data:
            return None

        row: dict[str, float] = {}
        for k in ("open", "high", "low", "close", "volume"):
            try:
                row[k] = float(data[k])
            except (KeyError, ValueError, TypeError):
                return None

        return pd.DataFrame([row])

    @staticmethod
    async def _persist_signal(sig) -> None:
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
                        "regime": "",
                        "metadata": json.dumps({}),
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.warning("signal_persist_error", symbol=sig.symbol, error=str(exc))
