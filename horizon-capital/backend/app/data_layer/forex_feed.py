"""Forex feed -- USD/INR rate from Yahoo Finance, cached in Redis."""

from __future__ import annotations

import asyncio

import yfinance as yf

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger

logger = get_logger(__name__)

_REDIS_KEY = "horizon:forex:usdinr"
_REFRESH_INTERVAL = 300  # 5 minutes


class ForexFeed:
    """Polls USD/INR via yfinance and caches the latest rate in Redis.

    This is intentionally *not* a ``BaseFeed`` subclass because it serves a
    single FX pair and does not emit generic tick / OHLCV callbacks.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_rate: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("forex_feed.started", pair="USDINR")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("forex_feed.stopped")

    async def get_rate(self) -> float | None:
        """Return cached USD/INR rate from Redis (or in-memory fallback)."""
        cached = await get_kv_store().get(_REDIS_KEY)
        if cached:
            return float(cached)
        return self._last_rate

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------
    async def _poll_loop(self) -> None:
        while self._running:
            try:
                rate = await self._fetch_rate()
                if rate is not None:
                    self._last_rate = rate
                    await get_kv_store().set(_REDIS_KEY, str(rate))
                    logger.info("forex_feed.updated", usdinr=rate)
            except Exception:
                logger.exception("forex_feed.poll_error")
            await asyncio.sleep(_REFRESH_INTERVAL)

    async def _fetch_rate(self) -> float | None:
        """Fetch current USD/INR rate via yfinance (blocking call in executor)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_sync)

    @staticmethod
    def _fetch_sync() -> float | None:
        try:
            ticker = yf.Ticker("USDINR=X")
            hist = ticker.history(period="1d", interval="1m")
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[-1])
            # Fallback: use fast_info
            info = ticker.fast_info
            price = getattr(info, "last_price", None)
            return float(price) if price else None
        except Exception:
            logger.exception("forex_feed.fetch_sync_error")
            return None
