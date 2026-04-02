"""CoinGecko REST feed -- polls BTC / ETH prices every 60 seconds."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedTick

logger = get_logger(__name__)

_COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

# Internal symbol -> CoinGecko id
_SYMBOL_TO_CG_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
}


class CryptoFeed(BaseFeed):
    """Free CoinGecko REST polling feed for crypto spot prices."""

    def __init__(self) -> None:
        super().__init__(name="crypto")
        self._symbols: list[str] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._poll_interval: int = 60  # seconds

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        self._is_connected = True
        logger.info("crypto_feed.connect")

    async def disconnect(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._is_connected = False
        logger.info("crypto_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        """Accept symbols like ``BTC-USD``, ``ETH-USD``."""
        self._symbols = [self._normalize_sym(s) for s in symbols]
        logger.info("crypto_feed.subscribe", symbols=self._symbols)

    async def start(self) -> None:
        if not self._is_connected:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    async def fetch_latest(self, symbol: str) -> None:
        """Fetch the latest price for *symbol*. Used by the ingestion worker."""
        async with httpx.AsyncClient(timeout=15) as client:
            await self._fetch_prices(client)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        logger.info("crypto_feed.poll_loop_started", interval=self._poll_interval)
        async with httpx.AsyncClient(timeout=15) as client:
            while self._running:
                try:
                    await self._fetch_prices(client)
                except Exception:
                    logger.exception("crypto_feed.poll_error")
                await asyncio.sleep(self._poll_interval)

    async def _fetch_prices(self, client: httpx.AsyncClient) -> None:
        cg_ids = []
        id_to_symbol: dict[str, str] = {}
        for sym in self._symbols:
            cg_id = _SYMBOL_TO_CG_ID.get(sym)
            if cg_id:
                cg_ids.append(cg_id)
                id_to_symbol[cg_id] = sym

        if not cg_ids:
            return

        params = {
            "ids": ",".join(cg_ids),
            "vs_currencies": "usd",
            "include_24hr_vol": "true",
            "include_last_updated_at": "true",
        }
        resp = await client.get(_COINGECKO_PRICE_URL, params=params)
        if resp.status_code != 200:
            logger.warning("crypto_feed.coingecko_error", status=resp.status_code)
            return

        data: dict[str, Any] = resp.json()
        for cg_id, info in data.items():
            symbol = id_to_symbol.get(cg_id)
            if symbol is None:
                continue
            price = info.get("usd")
            if price is None:
                continue

            ts = info.get("last_updated_at")
            timestamp = (
                datetime.fromtimestamp(ts, tz=UTC)
                if ts
                else datetime.now(UTC)
            )

            tick = NormalizedTick(
                symbol=f"{symbol}-USD",
                exchange="CRYPTO",
                timestamp=timestamp,
                last_price=float(price),
                volume=int(info.get("usd_24h_vol", 0)),
                currency="USD",
            )
            await self._emit_tick(tick)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_sym(symbol: str) -> str:
        """``BTC-USD`` -> ``BTC``, ``ETH`` -> ``ETH``."""
        return symbol.split("-")[0].upper()
