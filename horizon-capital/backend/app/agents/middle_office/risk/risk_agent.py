"""Risk Agent -- pre-trade validation and continuous portfolio risk monitoring."""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_kv():
    from app.core.kv_store import get_kv_store
    return get_kv_store()

logger = get_logger("agent.risk")


class RiskAgent(BaseAgent):
    """Monitors portfolio risk and enforces pre-trade limits.

    Subscribes to:
      - ``horizon.signal.*``            -- pre-trade validation
      - ``horizon.execution.order.*``   -- post-trade monitoring

    Publishes:
      - ``horizon.risk.alert``          -- when a limit is breached or signal is blocked
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="risk-agent",
            agent_type="risk",
            bus=bus,
        )
        self.redis = _get_kv()

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.signal.*", self.on_message)
        await self.bus.subscribe("horizon.execution.order.*", self.on_message)

    # ------------------------------------------------------------------ #
    # Main loop -- recompute risk metrics every 30 seconds
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Periodically recompute portfolio risk and persist metrics."""
        while self._running:
            try:
                await self._recompute_risk()
            except Exception as exc:
                logger.error("risk_recompute_error", error=str(exc))
            await asyncio.sleep(30)

    # ------------------------------------------------------------------ #
    # Message handler
    # ------------------------------------------------------------------ #

    async def on_message(self, message: AgentMessage) -> None:
        """Route incoming messages to the appropriate handler."""
        if message.channel.startswith("horizon.signal."):
            await self._handle_signal(message)
        elif message.channel.startswith("horizon.execution.order."):
            await self._handle_post_trade(message)

    # ------------------------------------------------------------------ #
    # Pre-trade validation
    # ------------------------------------------------------------------ #

    async def _handle_signal(self, message: AgentMessage) -> None:
        """Validate a proposed signal before it becomes an order."""
        payload = message.payload
        symbol = payload.get("symbol", "")

        violations: list[str] = []

        if not await self._check_position_limit(symbol):
            violations.append(
                f"Position in {symbol} would exceed "
                f"{settings.risk_max_position_pct}% limit"
            )

        if not await self._check_daily_loss_limit():
            violations.append(
                f"Daily loss exceeds {settings.risk_daily_loss_limit_pct}% limit"
            )

        if violations:
            await self.emit(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                payload={
                    "signal_id": payload.get("signal_id"),
                    "symbol": symbol,
                    "violations": violations,
                    "action": "REJECTED",
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            await self.emit(
                channel=f"horizon.risk.rejected.{symbol}",
                message_type=MessageType.RISK_ALERT,
                payload={
                    **payload,
                    "violations": violations,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning("signal_rejected", symbol=symbol, violations=violations)
        else:
            await self.emit(
                channel=f"horizon.risk.approved.{symbol}",
                message_type=MessageType.SIGNAL,
                payload={
                    **payload,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.info("signal_approved", symbol=symbol)

    # ------------------------------------------------------------------ #
    # Post-trade monitoring
    # ------------------------------------------------------------------ #

    async def _handle_post_trade(self, message: AgentMessage) -> None:
        """After a fill, immediately recompute risk."""
        try:
            await self._recompute_risk()
        except Exception as exc:
            logger.error("post_trade_risk_error", error=str(exc))

    # ------------------------------------------------------------------ #
    # Risk recomputation
    # ------------------------------------------------------------------ #

    async def _recompute_risk(self) -> None:
        """Compute historical VaR and drawdown, persist metrics."""
        returns = await self._load_portfolio_returns()
        equity_curve = await self._load_equity_curve()

        var_95 = self._compute_var(returns, confidence=0.95)
        max_dd = self._compute_max_drawdown(equity_curve)
        current_dd = self._compute_current_drawdown(equity_curve)

        now = datetime.now(UTC)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO risk_metrics
                        (id, var_1d_95, var_1d_99, cvar_1d_95,
                         max_drawdown, current_drawdown,
                         kill_switch_active, created_at, updated_at)
                    VALUES
                        (:id, :var_95, :var_99, :cvar_95,
                         :max_dd, :current_dd,
                         0, :now, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "var_95": var_95,
                    "var_99": var_95,
                    "cvar_95": var_95,
                    "max_dd": max_dd,
                    "current_dd": current_dd,
                    "now": now,
                },
            )
            await session.commit()

        await self.redis.hset(
            "horizon:risk:latest",
            mapping={
                "var_1d_95": str(var_95),
                "var_1d_99": str(var_95),
                "cvar_1d_95": str(var_95),
                "max_drawdown": str(max_dd),
                "current_drawdown": str(current_dd),
                "kill_switch_active": "0",
                "updated_at": now.isoformat(),
            },
        )

        logger.info(
            "risk_metrics_updated",
            var_95=f"{var_95:.4f}",
            current_dd=f"{current_dd:.4f}",
        )

    # ------------------------------------------------------------------ #
    # Simple risk checks
    # ------------------------------------------------------------------ #

    async def _check_position_limit(self, symbol: str) -> bool:
        """Return True if the position is within the 5% per-symbol limit."""
        nav_str = await self.redis.get("horizon:portfolio:nav")
        if not nav_str:
            return True
        nav = float(nav_str)
        if nav <= 0:
            return True

        async with _get_session_factory()() as session:
            row = await session.execute(
                text(
                    "SELECT quantity, current_price FROM positions "
                    "WHERE symbol = :symbol LIMIT 1"
                ),
                {"symbol": symbol},
            )
            pos = row.fetchone()

        if not pos:
            return True

        current_value = abs(pos.quantity * pos.current_price)
        weight_pct = (current_value / nav) * 100
        return weight_pct < settings.risk_max_position_pct

    async def _check_daily_loss_limit(self) -> bool:
        """Return True if daily loss is within the 10% limit."""
        nav_str = await self.redis.get("horizon:portfolio:nav")
        if not nav_str:
            return True
        nav = float(nav_str)
        if nav <= 0:
            return True

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized,
                           COALESCE(SUM(realized_pnl), 0) AS total_realized
                    FROM positions
                    """
                )
            )
            row = result.fetchone()

        total_pnl = (row.total_unrealized or 0) + (row.total_realized or 0)
        if total_pnl >= 0:
            return True

        loss_pct = abs(total_pnl) / nav * 100
        if loss_pct >= settings.risk_daily_loss_limit_pct:
            logger.warning(
                "daily_loss_limit_breach",
                loss_pct=f"{loss_pct:.2f}",
                limit=settings.risk_daily_loss_limit_pct,
            )
            return False
        return True

    # ------------------------------------------------------------------ #
    # VaR and drawdown helpers (historical simulation)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _compute_var(returns: list[float], confidence: float = 0.95) -> float:
        """Historical VaR at 95% confidence using percentile of returns."""
        if not returns:
            return 0.0
        sorted_returns = sorted(returns)
        idx = int((1 - confidence) * len(sorted_returns))
        idx = max(0, min(idx, len(sorted_returns) - 1))
        return abs(sorted_returns[idx])

    @staticmethod
    def _compute_max_drawdown(equity_curve: list[float]) -> float:
        """Maximum peak-to-trough drawdown as a fraction."""
        if len(equity_curve) < 2:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for val in equity_curve:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd
        return max_dd

    @staticmethod
    def _compute_current_drawdown(equity_curve: list[float]) -> float:
        """Current drawdown from the last peak."""
        if len(equity_curve) < 2:
            return 0.0
        peak = max(equity_curve)
        if peak == 0:
            return 0.0
        current = equity_curve[-1]
        return max((peak - current) / peak, 0.0)

    # ------------------------------------------------------------------ #
    # Data loaders
    # ------------------------------------------------------------------ #

    async def _load_portfolio_returns(self) -> list[float]:
        """Load recent portfolio daily returns from portfolio_snapshots."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT total_value
                    FROM portfolio_snapshots
                    ORDER BY created_at DESC
                    LIMIT 253
                    """
                )
            )
            rows = result.fetchall()

        if len(rows) < 2:
            return []

        values = [r.total_value for r in reversed(rows)]
        returns = []
        for i in range(1, len(values)):
            prev = values[i - 1]
            if prev != 0:
                returns.append((values[i] - prev) / prev)
        return returns

    async def _load_equity_curve(self) -> list[float]:
        """Load the equity curve for drawdown calculation."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT total_value
                    FROM portfolio_snapshots
                    ORDER BY created_at DESC
                    LIMIT 253
                    """
                )
            )
            rows = result.fetchall()

        if not rows:
            return []

        return [r.total_value for r in reversed(rows)]
