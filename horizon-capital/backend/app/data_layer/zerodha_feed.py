"""Zerodha / Kite feed -- mock-mode random ticks or real Kite WebSocket."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedTick

logger = get_logger(__name__)

# Seed prices for Indian equities (used only in mock mode)
_SEED_PRICES: dict[str, float] = {
    "RELIANCE": 2450.0,
    "TCS": 3600.0,
    "INFY": 1520.0,
    "HDFCBANK": 1650.0,
    "ICICIBANK": 1050.0,
    "WIPRO": 430.0,
    "SBIN": 620.0,
    "BAJFINANCE": 6800.0,
    "LT": 2700.0,
    "ITC": 440.0,
}


class ZerodhaFeed(BaseFeed):
    """Indian market feed via Zerodha Kite.

    When ``settings.zerodha_mock_mode`` is ``True`` (the default) the feed
    generates random ticks around the last known price so the rest of the
    platform can be developed / tested without a live Zerodha connection.
    """

    def __init__(self) -> None:
        super().__init__(name="zerodha")
        self._symbols: list[str] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # Track latest prices for mock jitter
        self._last_prices: dict[str, float] = dict(_SEED_PRICES)

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if settings.zerodha_mock_mode:
            logger.info("zerodha_feed.connect (mock mode)")
            self._is_connected = True
            return

        # TODO: real Kite WebSocket connection
        # from kiteconnect import KiteTicker
        # self._kws = KiteTicker(settings.zerodha_api_key, settings.zerodha_access_token)
        logger.info("zerodha_feed.connect (real mode -- placeholder)")
        self._is_connected = True

    async def disconnect(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._is_connected = False
        logger.info("zerodha_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = [self._strip_exchange(s) for s in symbols]
        logger.info("zerodha_feed.subscribe", symbols=self._symbols)

    async def start(self) -> None:
        if not self._is_connected:
            return
        self._running = True
        if settings.zerodha_mock_mode:
            self._task = asyncio.create_task(self._mock_loop())
        else:
            self._task = asyncio.create_task(self._real_loop())

    # ------------------------------------------------------------------
    # Mock mode
    # ------------------------------------------------------------------
    async def _mock_loop(self) -> None:
        """Generate random ticks every ~2 seconds for each subscribed symbol."""
        logger.info("zerodha_feed.mock_loop_started", symbols=self._symbols)
        while self._running:
            for symbol in self._symbols:
                tick = self._generate_mock_tick(symbol)
                await self._emit_tick(tick)
            await asyncio.sleep(2)

    def _generate_mock_tick(self, symbol: str) -> NormalizedTick:
        last = self._last_prices.get(symbol, 1000.0)
        # Random walk: up to +/- 0.3 %
        change_pct = random.uniform(-0.003, 0.003)
        new_price = round(last * (1 + change_pct), 2)
        self._last_prices[symbol] = new_price

        spread = round(new_price * 0.0005, 2)  # ~5 bps spread
        return NormalizedTick(
            symbol=symbol,
            exchange="NSE",
            timestamp=datetime.now(timezone.utc),
            last_price=new_price,
            bid=round(new_price - spread, 2),
            ask=round(new_price + spread, 2),
            volume=random.randint(100, 50000),
            currency="INR",
        )

    # ------------------------------------------------------------------
    # Real mode (placeholder)
    # ------------------------------------------------------------------
    async def _real_loop(self) -> None:
        """Placeholder for Kite WebSocket streaming.

        TODO: Implement using ``kiteconnect.KiteTicker``:
          1. Register on_ticks, on_connect, on_close callbacks.
          2. Convert raw Kite tick dicts to ``NormalizedTick``.
          3. Call ``self._emit_tick(tick)`` for each.
        """
        logger.warning("zerodha_feed.real_loop not implemented -- sleeping")
        while self._running:
            await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_exchange(symbol: str) -> str:
        return symbol.rsplit(".", 1)[0] if "." in symbol else symbol
