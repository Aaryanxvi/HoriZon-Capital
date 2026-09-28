# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-05F984F305E4
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Alpaca broker adapter -- places orders via the Alpaca Markets REST API."""

from datetime import UTC, datetime

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("execution.alpaca_broker")


def _is_crypto_symbol(symbol: str) -> bool:
    return symbol.endswith(("-USD", "-USDT"))


class AlpacaBroker:
    """Async broker that routes orders to Alpaca (paper or live).

    Configuration is read from ``settings``:
    - ``alpaca_api_key``
    - ``alpaca_api_secret``
    - ``alpaca_base_url`` (defaults to ``https://paper-api.alpaca.markets``)
    """

    def __init__(self) -> None:
        pass  # Credentials read dynamically from settings

    @property
    def base_url(self) -> str:
        return settings.alpaca_base_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def get_account(self) -> dict | None:
        """Fetch account info from Alpaca (equity, buying power, cash)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/account",
                    headers=self.headers,
                )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "account_number": data.get("account_number", ""),
                    "equity": float(data.get("equity", 0)),
                    "buying_power": float(data.get("buying_power", 0)),
                    "cash": float(data.get("cash", 0)),
                    "portfolio_value": float(data.get("portfolio_value", 0)),
                    "status": data.get("status", ""),
                    "currency": data.get("currency", "USD"),
                    "pattern_day_trader": data.get("pattern_day_trader", False),
                }
            else:
                logger.error("alpaca_account_error", status_code=resp.status_code)
                return None
        except httpx.HTTPError as exc:
            logger.error("alpaca_account_http_error", error=str(exc))
            return None

    async def _clamp_to_available(self, alpaca_symbol: str, qty: float) -> float:
        """Cap a crypto SELL at the qty Alpaca says is actually sellable.

        Alpaca charges the crypto taker fee in the base asset: buying 0.00016 BTC
        leaves 0.0001596 BTC in the account. Selling the recorded position size
        then fails with "insufficient balance for BTC", so a full exit could
        never close — the fee makes local qty permanently larger than broker qty.
        Reads the whole position list and matches on the slash-stripped symbol:
        orders take ``BTC/USD`` but positions come back as ``BTCUSD``, so a
        per-symbol GET 404s. Fail-open on a read failure: send the original qty
        and let the broker decide.
        """
        wanted = alpaca_symbol.replace("/", "").upper()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/positions", headers=self.headers
                )
            if resp.status_code != 200:
                return float(qty)
            available = 0.0
            for pos in resp.json():
                if str(pos.get("symbol", "")).replace("/", "").upper() == wanted:
                    available = float(pos.get("qty_available", 0.0))
                    break
        except Exception as exc:
            logger.warning("alpaca_position_read_failed", error=str(exc))
            return float(qty)

        if available < float(qty):
            logger.info(
                "alpaca_sell_qty_clamped",
                symbol=alpaca_symbol, requested=float(qty), available=available,
            )
        return min(float(qty), available)

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

        is_crypto = _is_crypto_symbol(symbol)
        if is_crypto:
            alpaca_symbol = symbol.replace("-", "/")  # BTC-USD -> BTC/USD
            if side == "sell":
                qty = await self._clamp_to_available(alpaca_symbol, qty)
                if qty <= 0:
                    logger.error("alpaca_no_position_to_sell", symbol=alpaca_symbol)
                    return None

        payload: dict = {
            "symbol": alpaca_symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": "gtc" if is_crypto else "day",
        }

        # Idempotency: Alpaca rejects a duplicate client_order_id, so a retry
        # after a timeout-that-already-landed cannot double-fire the order.
        if order_id:
            payload["client_order_id"] = str(order_id)

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
                    "filled_at": data.get("filled_at") or datetime.now(UTC).isoformat(),
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

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order via Alpaca API."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self.headers,
                )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as exc:
            logger.error("alpaca_cancel_error", error=str(exc))
            return False

    async def get_positions(self) -> list[dict]:
        """Fetch current positions from Alpaca."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/positions",
                    headers=self.headers,
                )
            if resp.status_code == 200:
                positions = []
                for p in resp.json():
                    raw_sym = p["symbol"]
                    if p.get("asset_class") == "crypto":
                        if "/" in raw_sym:
                            raw_sym = raw_sym.replace("/", "-")
                        elif raw_sym.endswith("USD"):
                            raw_sym = f"{raw_sym[:-3]}-USD"
                    positions.append(
                        {
                            "symbol": raw_sym,
                            "qty": float(p["qty"]),
                            "avg_entry": float(p["avg_entry_price"]),
                            "current_price": float(p["current_price"]),
                            "side": "LONG" if float(p["qty"]) > 0 else "SHORT",
                        }
                    )
                return positions
            return []
        except httpx.HTTPError as exc:
            logger.error("alpaca_positions_error", error=str(exc))
            return []
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 05F984F305E4 - verify with scripts/authorship.py verify
