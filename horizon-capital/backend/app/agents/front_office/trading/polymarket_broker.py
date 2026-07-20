"""Polymarket broker adapter -- places FOK market orders via py-clob-client (Polygon)."""

import asyncio
import json
from datetime import UTC, datetime

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("execution.polymarket_broker")


def clob_client_available() -> bool:
    """Whether the optional py-clob-client dependency is installed."""
    try:
        import py_clob_client  # noqa: F401

        return True
    except ImportError:
        return False


class PolymarketBroker:
    """Async broker that places real orders on Polymarket's CLOB (Polygon chain_id 137).

    Requires ``POLYMARKET_REAL_TRADING=true``, a funded wallet key, and
    ``py-clob-client`` installed — see ``_polymarket_guard_ok`` in
    ``execution_agent.py`` for the full gate.
    """

    def __init__(self) -> None:
        self._client = None

    async def execute(self, order: dict) -> dict | None:
        """Place a FOK market order for a Polymarket YES token."""
        from app.core.kv_store import get_kv_store

        symbol = order.get("symbol", "")
        kv = get_kv_store()

        meta_raw = await kv.get(f"horizon:pm:meta:{symbol}")
        if not meta_raw:
            logger.error("polymarket_meta_missing", symbol=symbol)
            return None
        meta = json.loads(meta_raw)
        token_id = meta["token_id"]

        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
        except ImportError:
            logger.error("py_clob_client_unavailable")
            return None

        try:
            client = await self._get_client()
        except Exception:
            logger.exception("polymarket_order_error", symbol=symbol)
            return None

        price_raw = await kv.get(f"horizon:price:{symbol}")
        price = float(price_raw) if price_raw else 0.0
        qty = float(order["quantity"])
        side = order.get("side", "BUY")

        try:
            if side == "BUY":
                args = MarketOrderArgs(
                    token_id=token_id, amount=round(qty * price, 2), side="BUY"
                )
            else:
                args = MarketOrderArgs(token_id=token_id, amount=qty, side="SELL")

            loop = asyncio.get_event_loop()
            signed = await loop.run_in_executor(None, client.create_market_order, args)
            resp = await loop.run_in_executor(
                None, client.post_order, signed, OrderType.FOK
            )
        except Exception:
            logger.exception("polymarket_order_error", symbol=symbol)
            return None

        if not resp.get("success", resp.get("orderID")):
            logger.error("polymarket_order_error", symbol=symbol, response=resp)
            return None

        return {
            "order_id": order.get("id", ""),
            "broker_order_id": resp.get("orderID", ""),
            "filled_qty": qty,
            "fill_price": resp.get("price", price),
            "commission": 0.0,
            "slippage": 0.0,
            "filled_at": datetime.now(UTC).isoformat(),
            "broker": "POLYMARKET",
        }

    async def _get_client(self):
        """Build (and cache) the ClobClient. Sync SDK calls run in an executor."""
        if self._client is not None:
            return self._client

        from py_clob_client.client import ClobClient

        loop = asyncio.get_event_loop()

        def _build():
            client = ClobClient(
                "https://clob.polymarket.com",
                key=settings.polymarket_private_key,
                chain_id=137,
                signature_type=1,
                funder=settings.polymarket_funder_address,
            )
            client.set_api_creds(client.create_or_derive_api_creds())
            return client

        self._client = await loop.run_in_executor(None, _build)
        return self._client
