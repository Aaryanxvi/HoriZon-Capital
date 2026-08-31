"""Polymarket broker adapter -- places FOK market orders on the CLOB (Polygon).

Uses ``py-clob-client-v2``. The v1 client (``py-clob-client``, last release
0.34.6) is archived: after Polymarket's CLOB v2 migration the exchange rejects
every order it signs with ``invalid order version, please use the latest
clob-client``, so v1 cannot place a trade at all regardless of funding.
"""

import asyncio
import json
from datetime import UTC, datetime

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("execution.polymarket_broker")

_MIN_ORDER_USD = 1.0  # CLOB rejects anything smaller
_CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"


def clob_client_available() -> bool:
    """Whether the optional py-clob-client-v2 dependency is installed."""
    try:
        import py_clob_client_v2  # noqa: F401

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
            from py_clob_client_v2.clob_types import MarketOrderArgsV2, OrderType
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
        if price <= 0.0:
            # KV can be cold on the first tick after a restart. A BUY sized off a
            # zero price is a $0 order the CLOB rejects — ask the book directly.
            price = await self._midpoint(token_id)
        if price <= 0.0:
            logger.error("polymarket_no_price", symbol=symbol)
            return None

        qty = float(order["quantity"])
        side = order.get("side", "BUY")

        try:
            if side == "BUY":
                amount = round(qty * price, 2)
                if amount < _MIN_ORDER_USD:
                    logger.error(
                        "polymarket_order_below_minimum",
                        symbol=symbol, amount=amount, minimum=_MIN_ORDER_USD,
                    )
                    return None
                # v2 BUY amount is USDC; SELL amount is shares.
                args = MarketOrderArgsV2(
                    token_id=token_id, amount=amount, side="BUY",
                    order_type=OrderType.FOK,
                )
            else:
                args = MarketOrderArgsV2(
                    token_id=token_id, amount=qty, side="SELL",
                    order_type=OrderType.FOK,
                )

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

    async def _midpoint(self, token_id: str) -> float:
        """Live CLOB midpoint for a token, or 0.0 if it can't be read."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _CLOB_MIDPOINT_URL, params={"token_id": token_id}
                )
            if resp.status_code != 200:
                return 0.0
            return float(resp.json().get("mid") or 0.0)
        except Exception:
            logger.warning("polymarket_midpoint_error", token_id=token_id)
            return 0.0

    async def _get_client(self):
        """Build (and cache) the ClobClient. Sync SDK calls run in an executor."""
        if self._client is not None:
            return self._client

        from py_clob_client_v2.client import ClobClient

        loop = asyncio.get_event_loop()

        def _build():
            client = ClobClient(
                "https://clob.polymarket.com",
                chain_id=137,
                key=settings.polymarket_private_key,
                signature_type=settings.polymarket_signature_type,
                # None, not "": an empty funder reaches the EIP-712 address
                # encoder and dies with "Value `` cannot be encoded by
                # AddressEncoder". None means "sign for the signer's own address".
                funder=settings.polymarket_funder_address or None,
            )
            # Derive the existing L2 key for this wallet; first-ever use has
            # nothing to derive, so fall back to minting one.
            try:
                creds = client.derive_api_key()
            except Exception:
                creds = client.create_api_key()
            client.set_api_creds(creds)
            return client

        self._client = await loop.run_in_executor(None, _build)
        return self._client
