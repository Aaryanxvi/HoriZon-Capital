"""Polygon.io REST feed -- OHLCV aggregates via free tier."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedOHLCV, NormalizedTick

logger = get_logger(__name__)

_BASE_URL = "https://api.polygon.io"


class PolygonFeed(BaseFeed):
    """Polygon.io free-tier REST client.

    Only active when ``settings.polygon_api_key`` is set.  The free tier
    allows daily aggregates with a delay; no real-time WebSocket.
    """

    def __init__(self) -> None:
        super().__init__(name="polygon")
        self._symbols: list[str] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def _enabled(self) -> bool:
        return bool(settings.polygon_api_key)

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if not self._enabled:
            logger.info("polygon_feed.disabled -- no API key")
            return
        self._is_connected = True
        logger.info("polygon_feed.connect")

    async def disconnect(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._is_connected = False
        logger.info("polygon_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = [self._strip_exchange(s) for s in symbols]
        logger.info("polygon_feed.subscribe", symbols=self._symbols)

    async def start(self) -> None:
        if not self._is_connected:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    async def get_ohlcv(
        self,
        symbol: str,
        from_date: str | date,
        to_date: str | date,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> list[NormalizedOHLCV]:
        """Fetch OHLCV bars from the Polygon aggregates endpoint.

        Parameters
        ----------
        symbol : str
            Ticker symbol (e.g. ``AAPL``).
        from_date, to_date : str | date
            Date range in ``YYYY-MM-DD`` format.
        timespan : str
            ``minute``, ``hour``, ``day``, ``week``, ``month``.
        multiplier : int
            Size of the timespan multiplier.
        """
        clean = self._strip_exchange(symbol)
        from_str = str(from_date)
        to_str = str(to_date)

        url = (
            f"{_BASE_URL}/v2/aggs/ticker/{clean}/range"
            f"/{multiplier}/{timespan}/{from_str}/{to_str}"
        )
        params: dict[str, Any] = {
            "adjusted": "true",
            "sort": "asc",
            "apiKey": settings.polygon_api_key,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "polygon_feed.ohlcv_error",
                    status=resp.status_code,
                    body=resp.text[:300],
                )
                return []
            data = resp.json()

        results = data.get("results", [])
        bars: list[NormalizedOHLCV] = []
        for r in results:
            ts_ms = r.get("t", 0)
            bars.append(
                NormalizedOHLCV(
                    symbol=clean,
                    exchange="NASDAQ",
                    timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                    timeframe=f"{multiplier}{timespan[0]}",  # e.g. "1d"
                    open=float(r["o"]),
                    high=float(r["h"]),
                    low=float(r["l"]),
                    close=float(r["c"]),
                    volume=int(r.get("v", 0)),
                    currency="USD",
                )
            )
        logger.info("polygon_feed.fetched", symbol=clean, bars=len(bars))
        return bars

    async def get_last_trade(self, symbol: str) -> NormalizedTick | None:
        """Fetch the latest trade for *symbol*."""
        clean = self._strip_exchange(symbol)
        url = f"{_BASE_URL}/v2/last/trade/{clean}"
        params = {"apiKey": settings.polygon_api_key}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()

        result = data.get("results", {})
        if not result:
            return None

        ts_ns = result.get("t", 0)  # nanosecond timestamp
        return NormalizedTick(
            symbol=clean,
            exchange="NASDAQ",
            timestamp=datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc),
            last_price=float(result["p"]),
            volume=int(result.get("s", 0)),
            currency="USD",
        )

    # ------------------------------------------------------------------
    # Background polling
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        """Poll last trade for subscribed symbols every 60 seconds."""
        while self._running:
            for symbol in self._symbols:
                try:
                    tick = await self.get_last_trade(symbol)
                    if tick:
                        await self._emit_tick(tick)
                except Exception:
                    logger.exception("polygon_feed.poll_error", symbol=symbol)
            await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_exchange(symbol: str) -> str:
        return symbol.rsplit(".", 1)[0] if "." in symbol else symbol
