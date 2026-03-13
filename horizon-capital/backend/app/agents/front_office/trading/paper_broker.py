"""Paper (simulated) broker -- fills orders at the last known price with small random slippage."""

import random
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.logging import get_logger

logger = get_logger("execution.paper_broker")


class PaperBroker:
    """Simulated broker that fills every order immediately.

    Uses the last price cached in Redis (``horizon:price:<symbol>``) as the
    mid-price and adds a small random slippage between 0 % and 0.1 %.
    Commission is always zero.
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def execute(self, order: dict) -> dict:
        """Simulate order execution.

        Parameters
        ----------
        order:
            Dict with at least: ``symbol``, ``side``, ``quantity``.
            Optional: ``limit_price``.

        Returns
        -------
        dict
            Fill record with keys: ``order_id``, ``filled_qty``,
            ``fill_price``, ``commission``, ``slippage``, ``filled_at``.
        """
        symbol = order["symbol"]
        side = order.get("side", "BUY")
        quantity = order["quantity"]
        order_id = order.get("id", "")

        # Get last price from Redis
        last_price = await self._get_last_price(symbol)
        if last_price <= 0:
            logger.warning("no_price_for_paper_fill", symbol=symbol)
            return self._rejection(order_id, "No price available for paper fill")

        # Apply slippage: 0-0.1 % adverse
        slippage_pct = random.uniform(0.0, 0.001)
        if side == "BUY":
            fill_price = last_price * (1.0 + slippage_pct)
        else:
            fill_price = last_price * (1.0 - slippage_pct)

        slippage_amount = abs(fill_price - last_price) * quantity

        fill = {
            "order_id": order_id,
            "filled_qty": quantity,
            "fill_price": round(fill_price, 6),
            "commission": 0.0,
            "slippage": round(slippage_amount, 6),
            "filled_at": datetime.now(timezone.utc).isoformat(),
            "broker": "PAPER",
        }

        logger.info(
            "paper_fill",
            symbol=symbol,
            side=side,
            qty=quantity,
            price=fill["fill_price"],
            slippage_pct=f"{slippage_pct * 100:.4f}%",
        )

        return fill

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _get_last_price(self, symbol: str) -> float:
        """Read the cached last price from Redis."""
        val = await self.redis.get(f"horizon:price:{symbol}")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.0

    @staticmethod
    def _rejection(order_id: str, reason: str) -> dict:
        return {
            "order_id": order_id,
            "filled_qty": 0.0,
            "fill_price": 0.0,
            "commission": 0.0,
            "slippage": 0.0,
            "filled_at": datetime.now(timezone.utc).isoformat(),
            "broker": "PAPER",
            "rejected": True,
            "rejection_reason": reason,
        }
