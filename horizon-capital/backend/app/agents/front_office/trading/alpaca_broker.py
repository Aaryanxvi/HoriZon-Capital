"""Alpaca broker adapter -- places orders via the Alpaca Markets REST API."""

from datetime import datetime, timezone

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("execution.alpaca_broker")


class AlpacaBroker:
    """Async broker that routes orders to Alpaca (paper or live).

    Configuration is read from ``settings``:
    - ``alpaca_api_key``
    - ``alpaca_api_secret``
    - ``alpaca_base_url`` (defaults to ``https://paper-api.alpaca.markets``)
    """

    def __init__(self) -> None:
        self.base_url = settings.alpaca_base_url.rstrip("/")
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def execute(self, order: dict) -> dict | None:
        """Place an order via the Alpaca API.

        Parameters
        ----------
        order:
            Dict with: ``symbol``, ``side``, ``quantity``, ``order_type``.
            For LIMIT orders also include ``limit_price``.

        Returns
        -------
        dict | None
            Fill dict on success, or ``None`` if the request failed.
        """
        symbol = order["symbol"]
        side = order.get("side", "BUY").lower()
        qty = order["quantity"]
        order_type = order.get("order_type", "MARKET").lower()
        order_id = order.get("id", "")

        # Strip exchange suffix for Alpaca (e.g., AAPL.NASDAQ -> AAPL)
        alpaca_symbol = symbol.split(".")[0] if "." in symbol else symbol

        payload: dict = {
            "symbol": alpaca_symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }

        if order_type == "limit" and order.get("limit_price"):
            payload["limit_price"] = str(order["limit_price"])

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v2/orders",
                    json=payload,
                    headers=self.headers,
                )

            if response.status_code in (200, 201):
                data = response.json()
                broker_order_id = data.get("id", "")

                logger.info(
                    "alpaca_order_placed",
                    broker_order_id=broker_order_id,
                    symbol=alpaca_symbol,
                    side=side,
                    qty=qty,
                    status=data.get("status"),
                )

                # Alpaca orders are often not immediately filled; return what we know
                filled_qty = float(data.get("filled_qty") or 0)
                filled_avg = float(data.get("filled_avg_price") or 0)

                return {
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "filled_qty": filled_qty,
                    "fill_price": filled_avg,
                    "commission": 0.0,
                    "slippage": 0.0,
                    "filled_at": data.get("filled_at") or datetime.now(timezone.utc).isoformat(),
                    "broker": "ALPACA",
                    "alpaca_status": data.get("status"),
                }
            else:
                logger.error(
                    "alpaca_order_error",
                    status_code=response.status_code,
                    body=response.text,
                    symbol=alpaca_symbol,
                )
                return None

        except httpx.HTTPError as exc:
            logger.error("alpaca_http_error", error=str(exc), symbol=alpaca_symbol)
            return None

    # ------------------------------------------------------------------ #
    # Order status polling (for partial fills)
    # ------------------------------------------------------------------ #

    async def get_order_status(self, broker_order_id: str) -> dict | None:
        """Poll the Alpaca API for the current status of an order."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self.headers,
                )

            if response.status_code == 200:
                data = response.json()
                return {
                    "broker_order_id": broker_order_id,
                    "status": data.get("status"),
                    "filled_qty": float(data.get("filled_qty") or 0),
                    "filled_avg_price": float(data.get("filled_avg_price") or 0),
                    "filled_at": data.get("filled_at"),
                }
            else:
                logger.warning(
                    "alpaca_status_error",
                    broker_order_id=broker_order_id,
                    status_code=response.status_code,
                )
                return None

        except httpx.HTTPError as exc:
            logger.error("alpaca_status_http_error", error=str(exc))
            return None
