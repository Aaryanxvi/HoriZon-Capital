"""Risk Agent -- pre-trade validation and continuous portfolio risk monitoring."""

import asyncio
import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.middle_office.risk.kill_switch import KillSwitch
from app.agents.middle_office.risk.var_calculator import VaRCalculator
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
    """Monitors portfolio risk in real-time and enforces pre-trade limits.

    Subscribes to:
      - ``horizon.signal.*``            -- pre-trade validation
      - ``horizon.execution.order.*``   -- post-trade monitoring

    Publishes:
      - ``horizon.risk.alert``          -- when a limit is breached
      - ``horizon.risk.kill_switch``    -- via KillSwitch
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="risk-agent",
            agent_type="risk",
            bus=bus,
        )
        self.var_calculator = VaRCalculator()
        self.kill_switch = KillSwitch(bus=bus, redis=_get_kv())
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
        """Validate a proposed signal before it becomes an order.

        On approval: emits RISK_APPROVED so PortfolioAgent can size the order.
        On rejection: emits RISK_REJECTED (signal is blocked).
        """
        payload = message.payload
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)
        strength = payload.get("strength", 0.0)

        violations: list[str] = []

        # 1. Check position-size limit (max % of portfolio in one name)
        if not await self._check_position_limit(symbol, strength):
            violations.append(
                f"Position in {symbol} would exceed "
                f"{settings.risk_max_position_pct}% limit"
            )

        # 2. Check total gross exposure ceiling (leverage)
        if not await self._check_exposure_ceiling():
            violations.append(
                f"Gross leverage would exceed {settings.risk_max_leverage}x"
            )

        # 3. Check correlation -- reject if highly correlated with existing book
        if not await self._check_correlation(symbol, direction):
            violations.append(
                f"{symbol} is too correlated with existing positions"
            )

        # 4. Check kill switch
        if await self.kill_switch.is_active():
            violations.append("Kill switch is active -- no new orders allowed")

        # 5. Check daily loss limit
        if not await self._check_daily_loss_limit():
            violations.append(
                f"Daily loss exceeds {settings.risk_daily_loss_limit_pct}% limit"
            )

        # 6. Check order rate limit
        if not await self._check_order_rate_limit():
            violations.append(
                f"Order rate exceeds {settings.risk_max_orders_per_minute}/min limit"
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
                message_type=MessageType.RISK_REJECTED,
                payload={
                    **payload,
                    "violations": violations,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.warning("signal_rejected", symbol=symbol, violations=violations)
        else:
            # Gate passed -- emit RISK_APPROVED with full signal payload
            await self.emit(
                channel=f"horizon.risk.approved.{symbol}",
                message_type=MessageType.RISK_APPROVED,
                payload={
                    **payload,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            # Increment order count for rate limiting
            await self._increment_order_count()
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
        """Recompute VaR, drawdown, and check kill-switch thresholds."""
        returns = await self._load_portfolio_returns()
        equity_curve = await self._load_equity_curve()

        var_95 = self.var_calculator.compute_var(returns, confidence=0.95)
        var_99 = self.var_calculator.compute_var(returns, confidence=0.99)
        cvar_95 = self.var_calculator.compute_cvar(returns, confidence=0.95)
        max_dd = self.var_calculator.compute_max_drawdown(equity_curve)
        current_dd = self.var_calculator.compute_current_drawdown(equity_curve)

        kill_active = await self.kill_switch.is_active()

        # Check if we need to trigger kill switch
        triggered = await self.kill_switch.check_thresholds(
            drawdown=current_dd,
            var_95=var_95,
            var_99=var_99,
        )
        if triggered:
            kill_active = True

        # Persist to risk_metrics table
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
                         :kill_active, :now, :now)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "var_95": var_95,
                    "var_99": var_99,
                    "cvar_95": cvar_95,
                    "max_dd": max_dd,
                    "current_dd": current_dd,
                    "kill_active": kill_active,
                    "now": now,
                },
            )
            await session.commit()

        # Cache latest metrics in Redis for fast dashboard access
        await self.redis.hset(
            "horizon:risk:latest",
            mapping={
                "var_1d_95": str(var_95),
                "var_1d_99": str(var_99),
                "cvar_1d_95": str(cvar_95),
                "max_drawdown": str(max_dd),
                "current_drawdown": str(current_dd),
                "kill_switch_active": "1" if kill_active else "0",
                "updated_at": now.isoformat(),
            },
        )

        logger.info(
            "risk_metrics_updated",
            var_95=f"{var_95:.4f}",
            var_99=f"{var_99:.4f}",
            current_dd=f"{current_dd:.4f}",
            kill_switch=kill_active,
        )

    # ------------------------------------------------------------------ #
    # Pre-trade check helpers
    # ------------------------------------------------------------------ #

    async def _check_position_limit(self, symbol: str, strength: float) -> bool:
        """Return True if the proposed position would stay within limits."""
        nav_str = await self.redis.get("horizon:portfolio:nav")
        if not nav_str:
            return True  # no portfolio data yet -- allow
        nav = float(nav_str)
        if nav <= 0:
            return True

        # Look up current position value for this symbol
        async with _get_session_factory()() as session:
            row = await session.execute(
                text(
                    "SELECT quantity, current_price FROM positions "
                    "WHERE symbol = :symbol LIMIT 1"
                ),
                {"symbol": symbol},
            )
            pos = row.fetchone()

        current_value = 0.0
        if pos:
            current_value = abs(pos.quantity * pos.current_price)

        # Assume worst case: signal at max strength adds another risk_max_position_pct
        proposed_weight = (current_value / nav) * 100
        return proposed_weight < settings.risk_max_position_pct

    async def _check_exposure_ceiling(self) -> bool:
        """Return True if gross leverage is below the configured maximum."""
        leverage_str = await self.redis.hget("horizon:portfolio:latest", "gross_leverage")
        if not leverage_str:
            return True
        return float(leverage_str) < settings.risk_max_leverage

    async def _check_correlation(self, symbol: str, direction: int) -> bool:
        """Simple correlation guard -- reject if the symbol is already in the book
        with a large weight in the same direction.

        A full correlation-matrix check would use precomputed matrices; this is
        a pragmatic first implementation.
        """
        async with _get_session_factory()() as session:
            row = await session.execute(
                text(
                    "SELECT side, weight_pct FROM positions "
                    "WHERE symbol = :symbol LIMIT 1"
                ),
                {"symbol": symbol},
            )
            pos = row.fetchone()

        if pos is None:
            return True  # no existing position

        # If already holding > 3% in the same direction, flag as correlated
        same_direction = (
            (direction > 0 and pos.side == "LONG")
            or (direction < 0 and pos.side == "SHORT")
        )
        if same_direction and pos.weight_pct > 3.0:
            return False
        return True

    # ------------------------------------------------------------------ #
    # Daily loss limit and order rate limiting
    # ------------------------------------------------------------------ #

    async def _check_daily_loss_limit(self) -> bool:
        """Return True if daily realized+unrealized loss is within limit."""
        nav_str = await self.redis.get("horizon:portfolio:nav")
        if not nav_str:
            return True
        nav = float(nav_str)
        if nav <= 0:
            return True

        # Sum unrealized + realized losses from current positions
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
            return True  # No loss

        loss_pct = abs(total_pnl) / nav * 100
        if loss_pct >= settings.risk_daily_loss_limit_pct:
            logger.warning(
                "daily_loss_limit_breach",
                loss_pct=f"{loss_pct:.2f}",
                limit=settings.risk_daily_loss_limit_pct,
            )
            return False
        return True

    async def _check_order_rate_limit(self) -> bool:
        """Return True if order rate is within limit (max orders per minute)."""
        count_str = await self.redis.get("horizon:orders:count_minute")
        if not count_str:
            return True
        try:
            count = int(count_str)
        except (ValueError, TypeError):
            return True
        return count < settings.risk_max_orders_per_minute

    async def _increment_order_count(self) -> None:
        """Increment the per-minute order counter."""
        count_str = await self.redis.get("horizon:orders:count_minute")
        count = int(count_str) + 1 if count_str else 1
        await self.redis.set("horizon:orders:count_minute", str(count), ex=60)

    # ------------------------------------------------------------------ #
    # Data loaders
    # ------------------------------------------------------------------ #

    async def _load_portfolio_returns(self) -> np.ndarray:
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
            return np.array([], dtype=np.float64)

        # Rows are most-recent-first; reverse for chronological order
        values = np.array([r.total_value for r in reversed(rows)], dtype=np.float64)
        # Daily returns = pct_change
        returns = np.diff(values) / np.where(values[:-1] == 0, 1.0, values[:-1])
        return returns

    async def _load_equity_curve(self) -> np.ndarray:
        """Load the equity (NAV) curve for drawdown calculation."""
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
            return np.array([], dtype=np.float64)

        return np.array([r.total_value for r in reversed(rows)], dtype=np.float64)
