"""Alpha Monitor Agent — tracks per-strategy performance and detects alpha decay.

Subscribes to execution and signal channels, maintains rolling performance
metrics per strategy, and emits ALPHA_DECAY alerts when a strategy's edge
erodes beyond configurable thresholds.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.agents.base_agent import BaseAgent
from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger("alpha_monitor")

# Thresholds
SHARPE_DECAY_THRESHOLD = 0.5
WIN_RATE_DECAY_THRESHOLD = 0.50
ROLLING_WINDOW = 20
SNAPSHOT_INTERVAL = 300  # seconds


@dataclass
class StrategyPerformance:
    """Rolling performance tracker for a single strategy."""

    strategy_name: str
    returns: deque = field(default_factory=lambda: deque(maxlen=50))
    signals: deque = field(default_factory=lambda: deque(maxlen=50))
    wins: int = 0
    losses: int = 0
    total_trades: int = 0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades

    @property
    def rolling_sharpe(self) -> float:
        if len(self.returns) < 5:
            return 0.0
        arr = np.array(self.returns)
        mean = np.mean(arr)
        std = np.std(arr)
        if std == 0:
            return 0.0
        return float(mean / std * np.sqrt(252))

    @property
    def avg_signal_strength(self) -> float:
        if not self.signals:
            return 0.0
        return float(np.mean(self.signals))


class AlphaMonitorAgent(BaseAgent):
    """Monitors strategy performance and detects alpha decay."""

    def __init__(self, bus) -> None:
        super().__init__(
            agent_id="alpha-monitor-1",
            agent_type="alpha_monitor",
            bus=bus,
            department="middle_office",
        )
        self._trackers: dict[str, StrategyPerformance] = defaultdict(
            lambda: StrategyPerformance(strategy_name="unknown")
        )

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.execution.*", self.on_message)
        await self.bus.subscribe("horizon.signal.*", self.on_message)

    async def on_message(self, message: AgentMessage) -> None:
        if message.message_type == MessageType.SIGNAL:
            self._track_signal(message.payload)
        elif message.message_type == MessageType.ORDER_FILL:
            self._track_fill(message.payload)

    def _track_signal(self, payload: dict[str, Any]) -> None:
        strategy = payload.get("strategy_name", "unknown")
        strength = payload.get("strength", 0.0)
        if strategy not in self._trackers:
            self._trackers[strategy] = StrategyPerformance(strategy_name=strategy)
        self._trackers[strategy].signals.append(strength)

    def _track_fill(self, payload: dict[str, Any]) -> None:
        strategy = payload.get("strategy_name", "unknown")
        pnl = payload.get("pnl_realized", 0.0)
        if strategy not in self._trackers:
            self._trackers[strategy] = StrategyPerformance(strategy_name=strategy)
        tracker = self._trackers[strategy]
        tracker.returns.append(pnl)
        tracker.total_trades += 1
        if pnl > 0:
            tracker.wins += 1
        else:
            tracker.losses += 1

    async def run(self) -> None:
        while self._running:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            await self._check_alpha_decay()
            await self._publish_snapshots()

    async def _check_alpha_decay(self) -> None:
        for strategy, tracker in self._trackers.items():
            if tracker.total_trades < ROLLING_WINDOW:
                continue

            alerts: list[str] = []
            sharpe = tracker.rolling_sharpe
            win_rate = tracker.win_rate

            if sharpe < SHARPE_DECAY_THRESHOLD:
                alerts.append(f"Sharpe={sharpe:.2f} < {SHARPE_DECAY_THRESHOLD}")

            if win_rate < WIN_RATE_DECAY_THRESHOLD and tracker.total_trades >= 30:
                alerts.append(f"WinRate={win_rate:.1%} < {WIN_RATE_DECAY_THRESHOLD:.0%}")

            if alerts:
                logger.warning(
                    "alpha_decay_detected",
                    strategy=strategy,
                    sharpe=sharpe,
                    win_rate=win_rate,
                    alerts=alerts,
                )
                await self.emit(
                    channel="horizon.alpha.decay",
                    message_type=MessageType.ALPHA_DECAY,
                    payload={
                        "strategy": strategy,
                        "sharpe": round(sharpe, 4),
                        "win_rate": round(win_rate, 4),
                        "total_trades": tracker.total_trades,
                        "avg_signal_strength": round(tracker.avg_signal_strength, 4),
                        "alerts": alerts,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )

    async def _publish_snapshots(self) -> None:
        for strategy, tracker in self._trackers.items():
            if tracker.total_trades == 0:
                continue
            await self.emit(
                channel="horizon.alpha.snapshot",
                message_type=MessageType.ALPHA_SNAPSHOT,
                payload={
                    "strategy": strategy,
                    "sharpe": round(tracker.rolling_sharpe, 4),
                    "win_rate": round(tracker.win_rate, 4),
                    "total_trades": tracker.total_trades,
                    "avg_signal_strength": round(tracker.avg_signal_strength, 4),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

    def get_strategy_metrics(self) -> dict[str, dict[str, Any]]:
        """Return current metrics for all tracked strategies (for TUI display)."""
        result = {}
        for name, tracker in self._trackers.items():
            result[name] = {
                "sharpe": round(tracker.rolling_sharpe, 4),
                "win_rate": round(tracker.win_rate, 4),
                "total_trades": tracker.total_trades,
                "avg_signal_strength": round(tracker.avg_signal_strength, 4),
            }
        return result
