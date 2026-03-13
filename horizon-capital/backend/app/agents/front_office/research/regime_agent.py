"""Regime-detection agent.

Runs on a 60-second loop, computes the current market regime for each scope
(INDIA, US, CRYPTO) using a Hidden Markov Model, monitors for concept drift
via the LFR detector, and publishes changes on ``horizon.regime.update``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.research.drift_detector import LFRDriftDetector
from app.agents.front_office.research.hmm_model import HMMRegimeModel
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()
from app.core.messaging import AgentBus, AgentMessage, MessageType

logger = get_logger("regime.agent")

MARKET_SCOPES = ["INDIA", "US", "CRYPTO"]
REGIME_CHANNEL = "horizon.regime.update"
POLL_INTERVAL_SECONDS = 60


class RegimeAgent(BaseAgent):
    """Periodically classifies market regime per scope and broadcasts changes."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="regime-agent-1",
            agent_type="regime",
            bus=bus,
        )
        # One HMM + drift detector per market scope
        self._models: dict[str, HMMRegimeModel] = {
            scope: HMMRegimeModel() for scope in MARKET_SCOPES
        }
        self._drift_detectors: dict[str, LFRDriftDetector] = {
            scope: LFRDriftDetector() for scope in MARKET_SCOPES
        }
        # Cache last published regime per scope to detect changes
        self._last_regime: dict[str, str] = {}

    # ------------------------------------------------------------------
    # BaseAgent hooks
    # ------------------------------------------------------------------

    async def _subscribe(self) -> None:
        """Subscribe to feature updates so we can feed the drift detector."""
        await self.bus.subscribe("horizon.features.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        """Handle incoming feature-update messages for drift detection feedback."""
        if message.message_type != MessageType.FEATURE_UPDATE:
            return
        # If the payload contains drift-feedback keys, feed the detector
        payload = message.payload
        scope = payload.get("market_scope")
        if scope and scope in self._drift_detectors:
            if "prediction_correct" in payload:
                self._drift_detectors[scope].update(
                    prediction_correct=payload["prediction_correct"],
                    predicted_positive=payload.get("predicted_positive", True),
                    actual_positive=payload.get("actual_positive", True),
                )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Every 60 s, compute regime for each scope and publish changes."""
        # On first run, attempt to load / train models
        await self._initialise_models()

        while self._running:
            for scope in MARKET_SCOPES:
                try:
                    await self._evaluate_scope(scope)
                except Exception as exc:
                    logger.error("regime_eval_error", scope=scope, error=str(exc))

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Per-scope evaluation
    # ------------------------------------------------------------------

    async def _evaluate_scope(self, scope: str) -> None:
        """Run regime detection for a single market scope."""
        features = await self._fetch_recent_features(scope)
        if features is None or len(features) < 2:
            return

        model = self._models[scope]
        if not model._fitted:
            # Not enough data or model not yet trained -- fall back to NEUTRAL
            regime, confidence = "NEUTRAL", 0.5
        else:
            regime, confidence = model.predict(features)

        # Check drift
        drift_level, drift_details = self._drift_detectors[scope].check_drift()
        if drift_level == "DRIFT":
            logger.warning(
                "drift_confirmed",
                scope=scope,
                regime=regime,
                details=drift_details,
            )
            # Increase uncertainty -- clamp confidence
            confidence = min(confidence, 0.4)
            self._drift_detectors[scope].reset()
        elif drift_level == "WARNING":
            logger.info("drift_warning_active", scope=scope)
            confidence = min(confidence, 0.6)

        # Persist to regime_states table
        await self._persist_regime(scope, regime, confidence)

        # Publish if regime changed
        prev = self._last_regime.get(scope)
        if regime != prev:
            logger.info(
                "regime_change",
                scope=scope,
                prev=prev,
                new=regime,
                confidence=confidence,
            )
            await self.emit(
                channel=REGIME_CHANNEL,
                message_type=MessageType.REGIME_UPDATE,
                payload={
                    "market_scope": scope,
                    "regime": regime,
                    "confidence": round(confidence, 4),
                    "previous_regime": prev,
                    "drift_level": drift_level,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            self._last_regime[scope] = regime

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    async def _fetch_recent_features(self, scope: str) -> np.ndarray | None:
        """Load the most recent return + volatility features from the DB.

        Fetches the last 60 OHLCV records for a representative symbol of the
        scope and computes log-returns + rolling volatility.
        """
        symbol_map = {
            "INDIA": "RELIANCE.NSE",
            "US": "AAPL.NASDAQ",
            "CRYPTO": "BTC-USD",
        }
        symbol = symbol_map.get(scope)
        if not symbol:
            return None

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT close FROM ohlcv
                    WHERE symbol = :symbol
                    ORDER BY timestamp DESC
                    LIMIT 60
                    """
                ),
                {"symbol": symbol},
            )
            rows = result.scalars().all()

        if len(rows) < 5:
            return None

        closes = np.array(list(reversed(rows)), dtype=np.float64)
        returns = np.diff(np.log(closes))
        window = min(20, len(returns))
        rolling_vol = np.array(
            [np.std(returns[max(0, i - window) : i + 1]) for i in range(len(returns))]
        )
        return np.column_stack([returns, rolling_vol])

    async def _persist_regime(self, scope: str, regime: str, confidence: float) -> None:
        """Insert a new row into ``regime_states``."""
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO regime_states (id, regime, confidence, method, market_scope, created_at)
                    VALUES (uuid_generate_v4(), :regime, :confidence, 'HMM', :scope, :now)
                    """
                ),
                {
                    "regime": regime,
                    "confidence": round(confidence, 4),
                    "scope": scope,
                    "now": datetime.now(timezone.utc),
                },
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def _initialise_models(self) -> None:
        """Try to train HMMs from existing historical data."""
        for scope in MARKET_SCOPES:
            try:
                features = await self._fetch_recent_features(scope)
                if features is not None and len(features) >= 30:
                    self._models[scope].train(features[:, 0])  # train on returns column
                    logger.info("hmm_initialised", scope=scope, n_samples=len(features))
                else:
                    logger.info("hmm_deferred", scope=scope, reason="insufficient_data")
            except Exception as exc:
                logger.warning("hmm_init_error", scope=scope, error=str(exc))
