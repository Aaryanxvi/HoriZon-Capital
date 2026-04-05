"""Adaptation Engine — responds to alpha decay and regime transitions.

A service (not an agent) that listens for alpha decay and regime transition
events and triggers automatic strategy adaptation: weight adjustments,
correlation recalibration, and position sizing changes.

All adaptation decisions are logged for audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger("services.adaptation")


class AdaptationEngine:
    """Stateful service that processes decay/transition events and emits adaptation actions."""

    def __init__(self, bus) -> None:
        self.bus = bus
        self._strategy_weights: dict[str, float] = {
            "momentum": 1.0,
            "mean_reversion": 1.0,
            "volatility": 1.0,
            "crisis": 1.0,
        }
        self._signal_threshold: float = 0.3  # minimum signal strength
        self._adaptation_log: list[dict[str, Any]] = []
        self._active = False

    async def start(self) -> None:
        """Subscribe to relevant channels and begin listening."""
        self._active = True
        await self.bus.subscribe("horizon.alpha.decay", self._on_alpha_decay)
        await self.bus.subscribe("horizon.regime.transition", self._on_regime_transition)
        logger.info("adaptation_engine_started")

    async def stop(self) -> None:
        self._active = False
        logger.info("adaptation_engine_stopped")

    async def _on_alpha_decay(self, message: AgentMessage) -> None:
        """Handle alpha decay: reduce weight of underperforming strategy."""
        if not self._active:
            return

        payload = message.payload
        strategy = payload.get("strategy", "")
        sharpe = payload.get("sharpe", 0.0)
        win_rate = payload.get("win_rate", 0.0)

        if strategy not in self._strategy_weights:
            return

        old_weight = self._strategy_weights[strategy]
        # Reduce weight by 25% on each decay alert, minimum 0.1
        new_weight = max(0.1, old_weight * 0.75)
        self._strategy_weights[strategy] = new_weight

        action = {
            "action": "reduce_strategy_weight",
            "strategy": strategy,
            "old_weight": round(old_weight, 4),
            "new_weight": round(new_weight, 4),
            "reason": f"Alpha decay: Sharpe={sharpe:.2f}, WinRate={win_rate:.1%}",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._adaptation_log.append(action)

        logger.info("adaptation_weight_reduced", **action)
        await self.bus.publish(
            AgentMessage(
                sender_id="adaptation-engine",
                channel="horizon.adaptation.action",
                message_type=MessageType.FEATURE_UPDATE,
                payload=action,
            )
        )

    async def _on_regime_transition(self, message: AgentMessage) -> None:
        """Handle regime transitions: adjust system parameters."""
        if not self._active:
            return

        payload = message.payload
        transition_type = payload.get("transition_type", "")
        to_regime = payload.get("to_regime", "")

        actions: list[dict[str, Any]] = []

        if transition_type == "volatility_shift":
            # Increase signal threshold during high vol
            if to_regime in ("HIGH_VOL", "HIGH_VOLATILITY"):
                old_thresh = self._signal_threshold
                self._signal_threshold = min(0.6, old_thresh + 0.1)
                actions.append({
                    "action": "increase_signal_threshold",
                    "old_value": round(old_thresh, 4),
                    "new_value": round(self._signal_threshold, 4),
                    "reason": f"Volatility shift to {to_regime}",
                })
            else:
                # Returning to normal vol — relax threshold
                old_thresh = self._signal_threshold
                self._signal_threshold = max(0.2, old_thresh - 0.05)
                actions.append({
                    "action": "decrease_signal_threshold",
                    "old_value": round(old_thresh, 4),
                    "new_value": round(self._signal_threshold, 4),
                    "reason": f"Volatility normalized to {to_regime}",
                })

        elif transition_type == "structural_break":
            # Reset all strategy weights on structural break
            for s in self._strategy_weights:
                self._strategy_weights[s] = 1.0
            actions.append({
                "action": "reset_strategy_weights",
                "reason": f"Structural break: {payload.get('from_regime')} -> {to_regime}",
            })
            # Increase threshold temporarily
            self._signal_threshold = min(0.5, self._signal_threshold + 0.15)
            actions.append({
                "action": "increase_signal_threshold",
                "new_value": round(self._signal_threshold, 4),
                "reason": "Structural break caution",
            })

        elif transition_type == "oscillation":
            # Reduce trade frequency by raising threshold
            old_thresh = self._signal_threshold
            self._signal_threshold = min(0.7, old_thresh + 0.2)
            actions.append({
                "action": "increase_signal_threshold",
                "old_value": round(old_thresh, 4),
                "new_value": round(self._signal_threshold, 4),
                "reason": "Regime oscillation — reducing trade frequency",
            })

        for action in actions:
            action["timestamp"] = datetime.now(UTC).isoformat()
            self._adaptation_log.append(action)

            logger.info("adaptation_action", **action)
            await self.bus.publish(
                AgentMessage(
                    sender_id="adaptation-engine",
                    channel="horizon.adaptation.action",
                    message_type=MessageType.FEATURE_UPDATE,
                    payload=action,
                )
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_strategy_weights(self) -> dict[str, float]:
        return dict(self._strategy_weights)

    def get_signal_threshold(self) -> float:
        return self._signal_threshold

    def get_adaptation_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self._adaptation_log[-limit:]))
