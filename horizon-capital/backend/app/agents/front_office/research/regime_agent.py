"""Regime-detection agent.

Runs on a 60-second loop, computes the current market regime for each scope
(INDIA, US, CRYPTO) using a Statistical Jump Model (primary) or Hidden Markov
Model (fallback), monitors for concept drift via the LFR detector, and
publishes changes on ``horizon.regime.update``.

References
----------
- Shu, Yu & Mulvey (2024), "Downside Risk Reduction Using Regime-Switching
  Signals: A Statistical Jump Model Approach", J. Asset Management.
- Hamilton (1989), "A New Approach to the Economic Analysis of Nonstationary
  Time Series", Econometrica (HMM foundational).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.research.drift_detector import LFRDriftDetector
from app.agents.front_office.research.hmm_model import HMMRegimeModel
from app.agents.front_office.research.jump_model import JumpRegimeModel
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()
from app.core.messaging import AgentBus, AgentMessage, MessageType  # noqa: E402

logger = get_logger("regime.agent")

MARKET_SCOPES = ["INDIA", "US", "CRYPTO"]
REGIME_CHANNEL = "horizon.regime.update"
REGIME_TRANSITION_CHANNEL = "horizon.regime.transition"
POLL_INTERVAL_SECONDS = 60

# Regime transition detection
VOLATILITY_SHIFT_THRESHOLD = 1.5  # ATR ratio for vol shift
OSCILLATION_WINDOW = 5  # regime changes within this count = oscillation


class RegimeAgent(BaseAgent):
    """Periodically classifies market regime per scope and broadcasts changes."""

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="regime-agent-1",
            agent_type="regime",
            bus=bus,
        )
        # Primary: Statistical Jump Model (Shu et al. 2024)
        # Fallback: HMM (Hamilton 1989) — only if hmmlearn is installed
        self._jump_models: dict[str, JumpRegimeModel] = {
            scope: JumpRegimeModel() for scope in MARKET_SCOPES
        }
        self._hmm_models: dict[str, HMMRegimeModel] = {
            scope: HMMRegimeModel() for scope in MARKET_SCOPES
        } if HMMRegimeModel.is_available() else {
        }
        self._drift_detectors: dict[str, LFRDriftDetector] = {
            scope: LFRDriftDetector() for scope in MARKET_SCOPES
        }
        # Which model backend is active per scope
        self._active_model: dict[str, str] = {}  # "jump" or "hmm"
        # Cache last published regime per scope to detect changes
        self._last_regime: dict[str, str] = {}
        # Track recent regime changes for oscillation detection
        self._regime_history: dict[str, list[str]] = {s: [] for s in MARKET_SCOPES}

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
        """Run regime detection for a single market scope.

        Prefers Statistical Jump Model (more persistent regimes, less
        initialization sensitivity) and falls back to HMM.
        """
        features = await self._fetch_recent_features(scope)
        if features is None or len(features) < 2:
            return

        # Try Jump Model first, then HMM
        regime: str = "NEUTRAL"
        confidence: float = 0.5
        method = self._active_model.get(scope, "none")

        if method == "jump" and self._jump_models[scope]._fitted:
            regime, confidence = self._jump_models[scope].predict(features)
        elif method == "hmm" and self._hmm_models[scope]._fitted:
            regime, confidence = self._hmm_models[scope].predict(features)
        else:
            # Neither model fitted
            regime, confidence = "NEUTRAL", 0.5

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
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Detect regime transitions
            await self._detect_transitions(scope, prev, regime, confidence)

            self._last_regime[scope] = regime

    # ------------------------------------------------------------------
    # Regime transition detection
    # ------------------------------------------------------------------

    async def _detect_transitions(
        self, scope: str, prev_regime: str | None, new_regime: str, confidence: float
    ) -> None:
        """Detect and emit regime transition events."""
        history = self._regime_history[scope]
        history.append(new_regime)
        # Keep only recent history
        if len(history) > 20:
            self._regime_history[scope] = history[-20:]
            history = self._regime_history[scope]

        transitions: list[dict] = []

        # Volatility regime shift: non-vol → HIGH_VOL or vice versa
        vol_regimes = {"HIGH_VOL", "HIGH_VOLATILITY"}
        if prev_regime and (
            (new_regime in vol_regimes and prev_regime not in vol_regimes)
            or (new_regime not in vol_regimes and prev_regime in vol_regimes)
        ):
            severity = min(confidence, 1.0)
            transitions.append({
                "transition_type": "volatility_shift",
                "from_regime": prev_regime,
                "to_regime": new_regime,
                "severity": round(severity, 4),
            })

        # Structural break: direct jump between opposing regimes
        opposing = {
            ("BULL", "CRISIS"), ("CRISIS", "BULL"),
            ("BULL", "BEAR"), ("BEAR", "BULL"),
        }
        if prev_regime and (prev_regime, new_regime) in opposing:
            transitions.append({
                "transition_type": "structural_break",
                "from_regime": prev_regime,
                "to_regime": new_regime,
                "severity": 0.8,
            })

        # Oscillation: too many regime changes in recent history
        if len(history) >= OSCILLATION_WINDOW:
            recent = history[-OSCILLATION_WINDOW:]
            unique_regimes = len(set(recent))
            if unique_regimes >= OSCILLATION_WINDOW - 1:
                transitions.append({
                    "transition_type": "oscillation",
                    "from_regime": prev_regime or "UNKNOWN",
                    "to_regime": new_regime,
                    "severity": 0.6,
                })

        for t in transitions:
            logger.info("regime_transition", scope=scope, **t)
            await self.emit(
                channel=REGIME_TRANSITION_CHANNEL,
                message_type=MessageType.REGIME_TRANSITION,
                payload={
                    "market_scope": scope,
                    **t,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

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
                    INSERT INTO regime_states
                        (id, regime, confidence, method, market_scope, created_at)
                    VALUES (:id, :regime, :confidence, :method, :scope, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "regime": regime,
                    "confidence": round(confidence, 4),
                    "method": self._active_model.get(scope, "HMM").upper(),
                    "scope": scope,
                    "now": datetime.now(UTC),
                },
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def _initialise_models(self) -> None:
        """Try to train regime models from existing historical data.

        Prefers Statistical Jump Model; falls back to HMM if jumpmodels
        is not installed or training fails.
        """
        for scope in MARKET_SCOPES:
            try:
                features = await self._fetch_recent_features(scope)
                if features is None or len(features) < 30:
                    logger.info("regime_model_deferred", scope=scope, reason="insufficient_data")
                    continue

                returns_col = features[:, 0]

                # Try Jump Model first (Shu et al. 2024)
                jm = self._jump_models[scope]
                if jm.is_available and len(returns_col) >= 50:
                    try:
                        jm.train(returns_col)
                        self._active_model[scope] = "jump"
                        logger.info(
                            "jump_model_initialised",
                            scope=scope,
                            n_samples=len(features),
                        )
                        continue
                    except Exception as exc:
                        logger.warning(
                            "jump_model_init_failed_falling_back_to_hmm",
                            scope=scope,
                            error=str(exc),
                        )

                # Fallback to HMM (Hamilton 1989)
                self._hmm_models[scope].train(returns_col)
                self._active_model[scope] = "hmm"
                logger.info("hmm_initialised", scope=scope, n_samples=len(features))

            except Exception as exc:
                logger.warning("regime_model_init_error", scope=scope, error=str(exc))
