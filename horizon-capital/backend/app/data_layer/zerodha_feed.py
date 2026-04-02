"""Zerodha / Kite feed -- mock-mode random ticks or real Kite WebSocket."""

from __future__ import annotations

import asyncio
import random
import threading
from datetime import UTC, datetime

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

# Lazy check for kiteconnect availability
_KITE_AVAILABLE: bool | None = None


def _check_kite() -> bool:
    global _KITE_AVAILABLE  # noqa: PLW0603
    if _KITE_AVAILABLE is None:
        try:
            from kiteconnect import KiteTicker  # noqa: F401
            _KITE_AVAILABLE = True
        except ImportError:
            _KITE_AVAILABLE = False
    return _KITE_AVAILABLE


# NSE instrument token map (common large-caps)
# In production these should be fetched from Kite instruments API
_INSTRUMENT_TOKENS: dict[str, int] = {
    "RELIANCE": 738561,
    "TCS": 2953217,
    "INFY": 408065,
    "HDFCBANK": 341249,
    "ICICIBANK": 1270529,
    "WIPRO": 969473,
    "SBIN": 779521,
    "BAJFINANCE": 81153,
    "LT": 2939649,
    "ITC": 424961,
}


class ZerodhaFeed(BaseFeed):
    """Indian market feed via Zerodha Kite.

    When ``settings.zerodha_mock_mode`` is ``True`` (the default) the feed
    generates random ticks around the last known price so the rest of the
    platform can be developed / tested without a live Zerodha connection.

    When mock mode is off and ``kiteconnect`` is installed, connects to the
    real Kite WebSocket for live NSE tick data.
    """

    def __init__(self) -> None:
        super().__init__(name="zerodha")
        self._symbols: list[str] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._kws = None
        self._kite_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Track latest prices for mock jitter
        self._last_prices: dict[str, float] = dict(_SEED_PRICES)
        # Reverse token → symbol map for real mode
        self._token_to_symbol: dict[int, str] = {}

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        if settings.zerodha_mock_mode:
            logger.info("zerodha_feed.connect", mode="mock")
            self._is_connected = True
            return

        if not settings.zerodha_api_key or not settings.zerodha_access_token:
            logger.error(
                "zerodha_feed.missing_credentials",
                hint="Set ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN in .env",
            )
            return

        if not _check_kite():
            logger.error(
                "zerodha_feed.kiteconnect_not_installed",
                hint="pip install kiteconnect",
            )
            return

        from kiteconnect import KiteTicker

        self._kws = KiteTicker(
            settings.zerodha_api_key,
            settings.zerodha_access_token,
        )
        self._is_connected = True
        logger.info("zerodha_feed.connect", mode="live")

    async def disconnect(self) -> None:
        self._running = False
        if self._kws is not None:
            try:
                self._kws.close()
            except Exception:
                pass
            self._kws = None
        if self._task and not self._task.done():
            self._task.cancel()
        if self._kite_thread and self._kite_thread.is_alive():
            self._kite_thread.join(timeout=5)
        self._is_connected = False
        logger.info("zerodha_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = [self._strip_exchange(s) for s in symbols]
        # Build token → symbol map
        self._token_to_symbol = {}
        for sym in self._symbols:
            token = _INSTRUMENT_TOKENS.get(sym)
            if token:
                self._token_to_symbol[token] = sym
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
            timestamp=datetime.now(UTC),
            last_price=new_price,
            bid=round(new_price - spread, 2),
            ask=round(new_price + spread, 2),
            volume=random.randint(100, 50000),
            currency="INR",
        )

    # ------------------------------------------------------------------
    # Real mode — KiteTicker WebSocket
    # ------------------------------------------------------------------
    async def _real_loop(self) -> None:
        """Connect to Kite WebSocket and stream live ticks.

        KiteTicker runs its own blocking event loop (Twisted/autobahn), so
        we start it in a background thread and feed ticks back to the async
        event loop via ``loop.call_soon_threadsafe``.
        """
        if self._kws is None:
            logger.error("zerodha_feed.real_loop_no_kws")
            return

        self._loop = asyncio.get_running_loop()
        tokens = list(self._token_to_symbol.keys())
        if not tokens:
            logger.warning(
                "zerodha_feed.no_instrument_tokens",
                symbols=self._symbols,
                hint="Subscribed symbols have no known instrument tokens",
            )
            return

        kws = self._kws

        def on_ticks(_ws, ticks: list[dict]) -> None:
            for tick_data in ticks:
                token = tick_data.get("instrument_token")
                sym = self._token_to_symbol.get(token)
                if sym is None:
                    continue
                normalized = NormalizedTick(
                    symbol=sym,
                    exchange="NSE",
                    timestamp=datetime.now(UTC),
                    last_price=float(tick_data.get("last_price", 0)),
                    bid=float(tick_data.get("depth", {}).get(
                        "buy", [{"price": 0}]
                    )[0].get("price", 0)),
                    ask=float(tick_data.get("depth", {}).get(
                        "sell", [{"price": 0}]
                    )[0].get("price", 0)),
                    volume=int(tick_data.get("volume_traded", 0)),
                    currency="INR",
                )
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        self._emit_tick(normalized),
                    )

        def on_connect(_ws, response) -> None:  # noqa: ARG001
            logger.info("zerodha_feed.kite_connected", tokens=len(tokens))
            kws.subscribe(tokens)
            kws.set_mode(kws.MODE_FULL, tokens)

        def on_close(_ws, code, reason) -> None:
            logger.warning(
                "zerodha_feed.kite_closed",
                code=code,
                reason=reason,
            )

        def on_error(_ws, code, reason) -> None:
            logger.error(
                "zerodha_feed.kite_error",
                code=code,
                reason=reason,
            )

        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_close = on_close
        kws.on_error = on_error

        # Run KiteTicker in a daemon thread (it blocks with Twisted reactor)
        def _run_kite() -> None:
            try:
                kws.connect(threaded=False)
            except Exception as exc:
                logger.error("zerodha_feed.kite_thread_error", error=str(exc))

        self._kite_thread = threading.Thread(
            target=_run_kite, daemon=True, name="kite-ticker"
        )
        self._kite_thread.start()
        logger.info("zerodha_feed.kite_thread_started")

        # Keep the async task alive while the thread runs
        while self._running:
            if self._kite_thread and not self._kite_thread.is_alive():
                logger.warning("zerodha_feed.kite_thread_died, reconnecting in 10s")
                await asyncio.sleep(10)
                if self._running:
                    self._kite_thread = threading.Thread(
                        target=_run_kite, daemon=True, name="kite-ticker"
                    )
                    self._kite_thread.start()
            await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_exchange(symbol: str) -> str:
        return symbol.rsplit(".", 1)[0] if "." in symbol else symbol
