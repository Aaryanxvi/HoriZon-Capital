"""Portfolio Agent -- capital allocation, position sizing, and NAV tracking."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import text

from app.agents.base_agent import BaseAgent
from app.agents.front_office.portfolio.currency import CurrencyConverter
from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer
from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentBus, AgentMessage, MessageType


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _get_redis():
    try:
        from app.core.redis_client import redis_client
        return redis_client
    except Exception:
        from app.core.kv_store import MemoryKVStore
        return MemoryKVStore()

logger = get_logger("agent.portfolio")


class PortfolioAgent(BaseAgent):
    """Manages capital allocation, position sizing, and portfolio snapshots.

    Subscribes to:
      - ``horizon.signal.*``  -- approved signals to compute position sizes

    Publishes:
      - ``horizon.portfolio.update``  -- after each snapshot refresh
    """

    def __init__(self, bus: AgentBus) -> None:
        super().__init__(
            agent_id="portfolio-agent",
            agent_type="portfolio",
            bus=bus,
        )
        self.optimizer = PortfolioOptimizer()
        self.currency = CurrencyConverter(redis=_get_redis())
        self.redis = _get_redis()

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def _subscribe(self) -> None:
        await self.bus.subscribe("horizon.signal.*", self.on_message)

    # ------------------------------------------------------------------ #
    # Main loop -- snapshot every 60 seconds
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        while self._running:
            try:
                await self._update_snapshot()
            except Exception as exc:
                logger.error("snapshot_error", error=str(exc))
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ #
    # Message handler
    # ------------------------------------------------------------------ #

    async def on_message(self, message: AgentMessage) -> None:
        """Handle approved signals -- compute position size and forward."""
        if message.message_type != MessageType.SIGNAL:
            return

        payload = message.payload
        symbol = payload.get("symbol", "")
        direction = payload.get("direction", 0)
        strength = payload.get("strength", 0.0)
        exchange = payload.get("exchange", "")

        if direction == 0:
            return

        try:
            sizing = await self._compute_position_size(symbol, direction, strength, exchange)
        except Exception as exc:
            logger.error("sizing_error", symbol=symbol, error=str(exc))
            return

        if sizing["quantity"] <= 0:
            logger.info("zero_size", symbol=symbol)
            return

        # Publish sized order request for execution agent
        await self.emit(
            channel=f"horizon.execution.order.new",
            message_type=MessageType.ORDER_NEW,
            payload={
                "symbol": symbol,
                "exchange": exchange,
                "side": "BUY" if direction > 0 else "SELL",
                "quantity": sizing["quantity"],
                "order_type": "MARKET",
                "signal_id": payload.get("signal_id"),
                "kelly_fraction": sizing["kelly_f"],
                "allocation_usd": sizing["allocation_usd"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        logger.info(
            "order_sized",
            symbol=symbol,
            side="BUY" if direction > 0 else "SELL",
            qty=sizing["quantity"],
            allocation=sizing["allocation_usd"],
        )

    # ------------------------------------------------------------------ #
    # Position sizing
    # ------------------------------------------------------------------ #

    async def _compute_position_size(
        self, symbol: str, direction: int, strength: float, exchange: str
    ) -> dict:
        """Determine how many shares/units to trade."""
        # Load current portfolio NAV
        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        nav = await self.currency.compute_unified_nav(cash_usd, cash_inr, positions)

        if nav <= 0:
            return {"quantity": 0.0, "kelly_f": 0.0, "allocation_usd": 0.0}

        # Use strength as a proxy for win-rate (clamped)
        win_rate = max(0.51, min(strength, 0.85))
        win_loss_ratio = 1.5  # default assumption

        kelly_f = self.optimizer.kelly_fraction(win_rate, win_loss_ratio)

        # Get current price from Redis
        price = await self._get_price(symbol)
        if price <= 0:
            return {"quantity": 0.0, "kelly_f": kelly_f, "allocation_usd": 0.0}

        # Compute raw quantity
        qty = self.optimizer.position_size(
            kelly_f=kelly_f,
            portfolio_value=nav,
            price=price,
            max_pct=settings.risk_max_position_pct / 100.0,
        )

        # Apply correlation penalty if we have existing positions
        held_symbols = [p.get("symbol", "") for p in positions if p.get("quantity", 0) != 0]
        if held_symbols:
            # Simplified: use a flat penalty based on number of correlated holdings
            # Full implementation would load a precomputed correlation matrix
            import numpy as np

            n = len(held_symbols) + 1
            corr = np.eye(n)  # identity = no correlation (conservative default)
            all_symbols = held_symbols + [symbol]
            penalty = self.optimizer.correlation_penalty(
                symbol=symbol,
                positions=held_symbols,
                correlation_matrix=corr,
                symbols_index=all_symbols,
            )
            qty *= penalty

        # For equities, round down to whole shares
        if exchange not in ("CRYPTO",):
            qty = float(int(qty))

        allocation_usd = qty * price

        return {
            "quantity": qty,
            "kelly_f": kelly_f,
            "allocation_usd": allocation_usd,
        }

    # ------------------------------------------------------------------ #
    # Snapshot persistence
    # ------------------------------------------------------------------ #

    async def _update_snapshot(self) -> None:
        """Compute and persist a portfolio snapshot."""
        positions = await self._load_positions()
        cash_usd, cash_inr = await self._load_cash()
        usd_inr = await self.currency.get_usd_inr_rate()
        nav = await self.currency.compute_unified_nav(cash_usd, cash_inr, positions)

        # Classify position values
        equity_value = 0.0
        crypto_value = 0.0
        fno_value = 0.0
        long_value = 0.0
        short_value = 0.0

        for pos in positions:
            val = abs(pos.get("current_price", 0.0) * pos.get("quantity", 0.0))
            currency = pos.get("currency", "USD")
            if currency == "INR":
                val = val / usd_inr if usd_inr > 0 else val
            exchange = pos.get("exchange", "")
            symbol = pos.get("symbol", "")

            if "BTC" in symbol or "ETH" in symbol or exchange == "CRYPTO":
                crypto_value += val
            elif exchange in ("NSE", "BSE"):
                equity_value += val
            else:
                equity_value += val

            side = pos.get("side", "LONG")
            if side == "LONG":
                long_value += val
            elif side == "SHORT":
                short_value += val

        gross_leverage = (long_value + short_value) / nav if nav > 0 else 0.0
        net_leverage = (long_value - short_value) / nav if nav > 0 else 0.0

        now = datetime.now(timezone.utc)
        async with _get_session_factory()() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO portfolio_snapshots
                        (id, total_value, cash_inr, cash_usd, equity_value,
                         crypto_value, fno_value, gross_leverage, net_leverage,
                         usd_inr_rate, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :total, :cash_inr, :cash_usd, :equity,
                         :crypto, :fno, :gross_lev, :net_lev,
                         :rate, :now, :now)
                    """
                ),
                {
                    "total": nav,
                    "cash_inr": cash_inr,
                    "cash_usd": cash_usd,
                    "equity": equity_value,
                    "crypto": crypto_value,
                    "fno": fno_value,
                    "gross_lev": gross_leverage,
                    "net_lev": net_leverage,
                    "rate": usd_inr,
                    "now": now,
                },
            )
            await session.commit()

        # Cache latest snapshot in Redis
        await self.redis.hset(
            "horizon:portfolio:latest",
            mapping={
                "total_value": str(nav),
                "cash_usd": str(cash_usd),
                "cash_inr": str(cash_inr),
                "gross_leverage": str(gross_leverage),
                "net_leverage": str(net_leverage),
                "updated_at": now.isoformat(),
            },
        )
        await self.redis.set("horizon:portfolio:nav", str(nav))

        # Publish update
        await self.emit(
            channel="horizon.portfolio.update",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload={
                "total_value": nav,
                "cash_usd": cash_usd,
                "cash_inr": cash_inr,
                "gross_leverage": gross_leverage,
                "net_leverage": net_leverage,
                "timestamp": now.isoformat(),
            },
        )

        logger.info("snapshot_updated", nav=f"{nav:.2f}", leverage=f"{gross_leverage:.2f}")

    # ------------------------------------------------------------------ #
    # Data helpers
    # ------------------------------------------------------------------ #

    async def _load_positions(self) -> list[dict]:
        """Load all open positions from the database."""
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT symbol, exchange, side, quantity, avg_entry_price,
                           current_price, unrealized_pnl, realized_pnl,
                           weight_pct, currency
                    FROM positions
                    WHERE quantity != 0
                    """
                )
            )
            rows = result.fetchall()

        return [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "side": r.side,
                "quantity": r.quantity,
                "avg_entry_price": r.avg_entry_price,
                "current_price": r.current_price,
                "unrealized_pnl": r.unrealized_pnl,
                "realized_pnl": r.realized_pnl,
                "weight_pct": r.weight_pct,
                "currency": r.currency,
            }
            for r in rows
        ]

    async def _load_cash(self) -> tuple[float, float]:
        """Load cash balances from Redis."""
        usd = await self.redis.get("horizon:cash:usd")
        inr = await self.redis.get("horizon:cash:inr")
        return float(usd or 0.0), float(inr or 0.0)

    async def _get_price(self, symbol: str) -> float:
        """Get latest price from Redis."""
        price = await self.redis.get(f"horizon:price:{symbol}")
        if price is not None:
            try:
                return float(price)
            except (ValueError, TypeError):
                pass
        return 0.0
