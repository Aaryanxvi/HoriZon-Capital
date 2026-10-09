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


def is_us_equity(symbol: str, exchange: str = "") -> bool:
    """True for a US-listed stock/ETF -- the only instruments Alpaca may route.

    Crypto, Polymarket and NSE/BSE names are excluded by suffix AND exchange so
    a mislabelled order cannot slip through on one of the two.
    """
    if _is_crypto_symbol(symbol) or symbol.endswith(".POLY"):
        return False
    if symbol.endswith((".NSE", ".BSE", ".NS", ".BO")):
        return False
    return exchange.upper() not in ("NSE", "BSE", "CRYPTO", "POLY")


def _qty_str(qty: float) -> str:
    """Alpaca treats "10.0" as a fractional request; whole shares go as "10"."""
    q = float(qty)
    return str(int(q)) if q == int(q) else str(q)


def _parse_order(data: dict) -> dict:
    """Shape every Alpaca order payload the same way for the agent."""
    return {
        "broker_order_id": data.get("id", ""),
        "client_order_id": data.get("client_order_id", ""),
        "symbol": data.get("symbol", ""),
        "side": data.get("side", ""),
        "type": data.get("type") or data.get("order_type"),
        "status": data.get("status"),
        "qty": float(data.get("qty") or 0),
        "filled_qty": float(data.get("filled_qty") or 0),
        "filled_avg_price": float(data.get("filled_avg_price") or 0),
        "filled_at": data.get("filled_at"),
        "hwm": float(data["hwm"]) if data.get("hwm") else None,
        "stop_price": float(data["stop_price"]) if data.get("stop_price") else None,
    }


# Alpaca statuses after which an order can no longer fill.
TERMINAL_STATUSES = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})


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
            "qty": _qty_str(qty),
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

        data = await self._post_order(payload)
        if data is None:
            return None
        parsed = _parse_order(data)
        logger.info(
            "alpaca_order_placed",
            broker_order_id=parsed["broker_order_id"], symbol=alpaca_symbol,
            side=side, qty=qty, status=parsed["status"],
        )
        # Alpaca orders are often not immediately filled; return what we know
        return {
            "order_id": order_id,
            "broker_order_id": parsed["broker_order_id"],
            "filled_qty": parsed["filled_qty"],
            "fill_price": parsed["filled_avg_price"],
            "commission": 0.0,
            "slippage": 0.0,
            "filled_at": parsed["filled_at"] or datetime.now(UTC).isoformat(),
            "broker": "ALPACA",
            "alpaca_status": parsed["status"],
        }

    async def place_trailing_stop(
        self, symbol: str, qty: float, trail_percent: float, client_order_id: str,
    ) -> dict | None:
        """Rest a GTC trailing-stop SELL at Alpaca for a long US equity.

        Alpaca fields (docs.alpaca.markets/reference/postorder): ``type``
        ``trailing_stop``, ``trail_percent`` (or ``trail_price``), ``time_in_force``
        ``day``|``gtc``. Fractional qty is NOT accepted for trailing stops, so
        the caller passes whole shares. Returns the parsed order or None.
        """
        whole = int(qty)
        if whole < 1 or not is_us_equity(symbol):
            return None
        payload = {
            "symbol": symbol.split(".")[0],
            "qty": str(whole),
            "side": "sell",
            "type": "trailing_stop",
            "trail_percent": str(round(float(trail_percent), 2)),
            "time_in_force": "gtc",
            "client_order_id": client_order_id,
        }
        data = await self._post_order(payload)
        if data is None:
            return None
        parsed = _parse_order(data)
        logger.info(
            "alpaca_trailing_stop_placed",
            broker_order_id=parsed["broker_order_id"], symbol=payload["symbol"],
            qty=whole, trail_percent=trail_percent, status=parsed["status"],
        )
        return parsed

    async def _post_order(self, payload: dict) -> dict | None:
        """POST /v2/orders. None on HTTP error or non-2xx (caller decides)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v2/orders", json=payload, headers=self.headers,
                )
            if response.status_code in (200, 201):
                return response.json()
            logger.error(
                "alpaca_order_error",
                status_code=response.status_code, body=response.text,
                symbol=payload.get("symbol"), type=payload.get("type"),
            )
            return None
        except httpx.HTTPError as exc:
            logger.error("alpaca_http_error", error=str(exc), symbol=payload.get("symbol"))
            return None

    async def get_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Resolve an order by OUR id after an ambiguous POST (timeout etc.).

        GET /v2/orders:by_client_order_id?client_order_id=... Returns the
        parsed order with ``found=True``, ``{"found": False}`` on a definitive
        404 (the POST never landed), or None when the broker is unreachable --
        callers must NOT treat None as "not placed".
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/v2/orders:by_client_order_id",
                    params={"client_order_id": client_order_id},
                    headers=self.headers,
                )
            if resp.status_code == 200:
                return {**_parse_order(resp.json()), "found": True}
            if resp.status_code == 404:
                return {"found": False}
            logger.warning(
                "alpaca_lookup_error", client_order_id=client_order_id,
                status_code=resp.status_code,
            )
            return None
        except httpx.HTTPError as exc:
            logger.error("alpaca_lookup_http_error", error=str(exc))
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
                return {**_parse_order(response.json()), "broker_order_id": broker_order_id}
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

    async def cancel_and_wait(self, broker_order_id: str, timeout_sec: float = 5.0) -> dict | None:
        """Cancel an order and wait until Alpaca reports a terminal status.

        Cancellation is asynchronous at Alpaca; a SELL sent while a resting
        stop on the same shares is still ``pending_cancel`` is rejected for
        insufficient qty. Returns the final status dict (``filled`` means the
        stop fired while we were cancelling -- the caller must book it), or
        None if it never settled within the timeout.
        """
        await self.cancel_order(broker_order_id)
        import asyncio

        deadline = asyncio.get_event_loop().time() + timeout_sec
        while True:
            status = await self.get_order_status(broker_order_id)
            if status is not None and status.get("status") in TERMINAL_STATUSES:
                return status
            if asyncio.get_event_loop().time() >= deadline:
                return status
            await asyncio.sleep(0.5)

    async def get_positions(self) -> list[dict] | None:
        """Fetch current positions from Alpaca.

        Returns None when the broker did not answer (HTTP error or non-200) --
        distinct from an empty list, because the ledger sync treats the broker
        as the source of truth and must never read "unreachable" as "flat".
        """
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
                            "qty_available": float(p.get("qty_available") or p["qty"]),
                            "avg_entry": float(p["avg_entry_price"]),
                            "current_price": float(p["current_price"]),
                            "side": "LONG" if float(p["qty"]) > 0 else "SHORT",
                            "exchange": str(p.get("exchange") or ""),
                            "asset_class": str(p.get("asset_class") or "us_equity"),
                        }
                    )
                return positions
            logger.error("alpaca_positions_error", status_code=resp.status_code)
            return None
        except httpx.HTTPError as exc:
            logger.error("alpaca_positions_error", error=str(exc))
            return None

    async def get_position_qty(self, symbol: str) -> float | None:
        """Total long qty the broker holds for ``symbol`` (0 if none); None if unreachable."""
        positions = await self.get_positions()
        if positions is None:
            return None
        base = symbol.split(".")[0] if "." in symbol and not _is_crypto_symbol(symbol) else symbol
        for p in positions:
            if p["symbol"].upper() == base.upper():
                return float(p["qty"])
        return 0.0
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 05F984F305E4 - verify with scripts/authorship.py verify
