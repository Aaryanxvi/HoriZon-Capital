"""Zerodha (Kite Connect) broker adapter.

Full implementation for NSE/BSE trading via Kite Connect REST API.
Falls back to PaperBroker when mock_mode is True.

Kite Connect API docs: https://kite.trade/docs/connect/v3/
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("execution.zerodha_broker")


# Lazy import to avoid breaking LOCAL mode
def _get_paper_broker():
    from app.agents.front_office.trading.paper_broker import PaperBroker
    return PaperBroker()


# Kite Connect endpoints
_KITE_BASE_URL = "https://api.kite.trade"
_KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"

# Exchange mapping
_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",  # NSE Futures & Options
    "BFO": "BFO",  # BSE Futures & Options
    "MCX": "MCX",  # Multi Commodity Exchange
}

# Product types
_PRODUCT_CNC = "CNC"    # Cash and Carry (delivery)
_PRODUCT_MIS = "MIS"    # Margin Intraday Settlement
_PRODUCT_NRML = "NRML"  # Normal (F&O)


class ZerodhaBroker:
    """Broker adapter for Zerodha's Kite Connect API.

    When ``settings.zerodha_mock_mode`` is True (default), all orders
    are routed to PaperBroker. When False, uses real Kite Connect API.

    Authentication flow:
    1. User visits login URL → redirected with request_token
    2. Exchange request_token for access_token via API
    3. Use access_token for all subsequent API calls
    """

    def __init__(self) -> None:
        self._paper: object | None = None

    @property
    def mock_mode(self) -> bool:
        return settings.zerodha_mock_mode

    @property
    def api_key(self) -> str:
        return settings.zerodha_api_key

    @property
    def api_secret(self) -> str:
        return settings.zerodha_api_secret

    @property
    def access_token(self) -> str:
        return settings.zerodha_access_token

    @property
    def _headers(self) -> dict[str, str]:
        """Build Kite Connect authorization headers."""
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get_profile(self) -> dict | None:
        """Fetch user profile from Kite Connect."""
        if self.mock_mode:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_KITE_BASE_URL}/user/profile",
                    headers=self._headers,
                )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "user_id": data.get("user_id", ""),
                    "user_name": data.get("user_name", ""),
                    "email": data.get("email", ""),
                    "broker": data.get("broker", "ZERODHA"),
                    "exchanges": data.get("exchanges", []),
                }
            return None
        except httpx.HTTPError as exc:
            logger.error("kite_profile_error", error=str(exc))
            return None

    async def get_margins(self) -> dict | None:
        """Fetch account margins from Kite Connect."""
        if self.mock_mode:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_KITE_BASE_URL}/user/margins",
                    headers=self._headers,
                )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                equity = data.get("equity", {})
                return {
                    "equity_available": float(equity.get("available", {}).get("live_balance", 0)),
                    "equity_used": float(equity.get("utilised", {}).get("debits", 0)),
                    "equity_net": float(equity.get("net", 0)),
                    "currency": "INR",
                }
            return None
        except httpx.HTTPError as exc:
            logger.error("kite_margins_error", error=str(exc))
            return None

    async def execute(self, order: dict) -> dict | None:
        """Execute an order on NSE/BSE via Kite Connect."""
        if self.mock_mode:
            logger.info("zerodha_mock_mode", symbol=order.get("symbol"))
            if self._paper is None:
                self._paper = _get_paper_broker()
            fill = await self._paper.execute(order)
            if fill:
                fill["broker"] = "ZERODHA_MOCK"
            return fill

        return await self._place_kite_order(order)

    async def get_positions(self) -> list[dict]:
        """Fetch current positions from Kite Connect."""
        if self.mock_mode:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_KITE_BASE_URL}/portfolio/positions",
                    headers=self._headers,
                )

            if resp.status_code == 200:
                data = resp.json()
                positions = []
                for pos in data.get("data", {}).get("net", []):
                    if pos.get("quantity", 0) != 0:
                        positions.append({
                            "symbol": pos["tradingsymbol"],
                            "exchange": pos["exchange"],
                            "quantity": abs(pos["quantity"]),
                            "avg_price": pos.get("average_price", 0),
                            "pnl": pos.get("pnl", 0),
                            "product": pos.get("product", ""),
                        })
                return positions
            else:
                logger.error("kite_positions_error", status=resp.status_code)
                return []
        except httpx.HTTPError as exc:
            logger.error("kite_positions_http_error", error=str(exc))
            return []

    async def get_order_status(self, broker_order_id: str) -> dict | None:
        """Check order status via Kite Connect."""
        if self.mock_mode:
            return {"broker_order_id": broker_order_id, "status": "COMPLETE"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_KITE_BASE_URL}/orders/{broker_order_id}",
                    headers=self._headers,
                )

            if resp.status_code == 200:
                data = resp.json()
                orders = data.get("data", [])
                if orders:
                    latest = orders[-1]  # Most recent status
                    return {
                        "broker_order_id": broker_order_id,
                        "status": latest.get("status", "UNKNOWN"),
                        "filled_qty": latest.get("filled_quantity", 0),
                        "filled_avg_price": latest.get("average_price", 0),
                        "status_message": latest.get("status_message", ""),
                    }
            return None
        except httpx.HTTPError as exc:
            logger.error("kite_status_error", error=str(exc))
            return None

    async def get_holdings(self) -> list[dict]:
        """Fetch delivery holdings from Kite Connect."""
        if self.mock_mode:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_KITE_BASE_URL}/portfolio/holdings",
                    headers=self._headers,
                )

            if resp.status_code == 200:
                data = resp.json()
                return [
                    {
                        "symbol": h["tradingsymbol"],
                        "exchange": h["exchange"],
                        "quantity": h["quantity"],
                        "avg_price": h["average_price"],
                        "last_price": h.get("last_price", 0),
                        "pnl": h.get("pnl", 0),
                    }
                    for h in data.get("data", [])
                ]
            return []
        except httpx.HTTPError as exc:
            logger.error("kite_holdings_error", error=str(exc))
            return []

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order via Kite Connect."""
        if self.mock_mode:
            return True
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{_KITE_BASE_URL}/orders/regular/{broker_order_id}",
                    headers=self._headers,
                )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.error("kite_cancel_error", error=str(exc))
            return False

    # ------------------------------------------------------------------ #
    # Kite Connect order placement
    # ------------------------------------------------------------------ #

    async def _place_kite_order(self, order: dict) -> dict | None:
        """Place an order via Kite Connect REST API.

        POST /orders/regular
        """
        symbol = order["symbol"]
        side = order.get("side", "BUY")
        qty = order["quantity"]
        order_type = order.get("order_type", "MARKET")
        order_id = order.get("id", "")

        # Strip exchange suffix (e.g., RELIANCE.NSE -> RELIANCE)
        trading_symbol = symbol.split(".")[0] if "." in symbol else symbol
        exchange = symbol.split(".")[-1] if "." in symbol else "NSE"
        exchange = _EXCHANGE_MAP.get(exchange, "NSE")

        # Determine product type
        product = _PRODUCT_CNC  # Default: delivery
        if exchange in ("NFO", "BFO", "MCX"):
            product = _PRODUCT_NRML  # F&O use NRML

        # Map order type
        kite_order_type = "MARKET"
        if order_type == "LIMIT":
            kite_order_type = "LIMIT"
        elif order_type == "SL":
            kite_order_type = "SL"
        elif order_type == "SL-M":
            kite_order_type = "SL-M"

        # Build form data (Kite uses form-encoded, not JSON)
        form_data = {
            "tradingsymbol": trading_symbol,
            "exchange": exchange,
            "transaction_type": side,
            "order_type": kite_order_type,
            "quantity": str(int(qty)),
            "product": product,
            "validity": "DAY",
        }

        if kite_order_type == "LIMIT" and order.get("limit_price"):
            form_data["price"] = str(order["limit_price"])
        if kite_order_type in ("SL", "SL-M") and order.get("stop_price"):
            form_data["trigger_price"] = str(order["stop_price"])

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_KITE_BASE_URL}/orders/regular",
                    data=form_data,
                    headers=self._headers,
                )

            if resp.status_code == 200:
                data = resp.json()
                broker_order_id = data.get("data", {}).get("order_id", "")

                logger.info(
                    "kite_order_placed",
                    broker_order_id=broker_order_id,
                    symbol=trading_symbol,
                    exchange=exchange,
                    side=side,
                    qty=qty,
                )

                # Kite doesn't return fill info immediately — poll for it
                fill_info = await self._poll_fill(broker_order_id)

                return {
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "filled_qty": fill_info.get("filled_qty", 0),
                    "fill_price": fill_info.get("filled_avg_price", 0),
                    "commission": 0.0,  # Zerodha: zero brokerage on delivery
                    "slippage": 0.0,
                    "filled_at": datetime.now(UTC).isoformat(),
                    "broker": "ZERODHA",
                    "kite_status": fill_info.get("status", "OPEN"),
                }
            else:
                error_msg = resp.json().get("message", resp.text) if resp.text else "Unknown error"
                logger.error(
                    "kite_order_error",
                    status_code=resp.status_code,
                    error=error_msg,
                    symbol=trading_symbol,
                )
                return {
                    "order_id": order_id,
                    "rejected": True,
                    "rejection_reason": f"Kite API error: {error_msg}",
                }

        except httpx.HTTPError as exc:
            logger.error("kite_http_error", error=str(exc), symbol=trading_symbol)
            return None

    async def _poll_fill(self, broker_order_id: str, max_attempts: int = 30) -> dict:
        """Poll Kite Connect for fill status (orders aren't filled instantly)."""
        import asyncio
        for attempt in range(max_attempts):
            await asyncio.sleep(1)  # Wait 1 second between polls
            status = await self.get_order_status(broker_order_id)
            if status and status.get("status") in ("COMPLETE", "CANCELLED", "REJECTED"):
                return status
        return {"status": "OPEN", "filled_qty": 0, "filled_avg_price": 0}
