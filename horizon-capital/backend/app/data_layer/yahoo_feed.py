# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-9CF1BC92CEB3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Yahoo Finance feed -- historical OHLCV polling via yfinance."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import yfinance as yf

from app.core.logging import get_logger
from app.data_layer.base_feed import BaseFeed
from app.data_layer.data_normalizer import NormalizedOHLCV

logger = get_logger(__name__)

# Suffix -> exchange mapping for yfinance tickers
_SUFFIX_EXCHANGE_MAP: dict[str, str] = {
    ".NS": "NSE",
    ".BO": "BSE",
    ".L": "LSE",
    ".HK": "HKEX",
    ".T": "TSE",
    ".SS": "SSE",
    ".SZ": "SZSE",
    ".AX": "ASX",
    ".TO": "TSX",
    ".DE": "XETRA",
    ".PA": "EURONEXT",
}


def _exchange_for_symbol(yf_symbol: str) -> str:
    """Derive exchange code from the yfinance symbol suffix."""
    for suffix, exchange in _SUFFIX_EXCHANGE_MAP.items():
        if yf_symbol.upper().endswith(suffix.upper()):
            return exchange
    # Crypto tickers typically end with -USD
    if "-" in yf_symbol:
        return "CRYPTO"
    # No suffix -> assume NASDAQ for US equities
    return "NASDAQ"


# Exchange UTC trading hours: (open_hour, open_min, close_hour, close_min)
_EXCHANGE_UTC_HOURS: dict[str, tuple[int, int, int, int]] = {
    "NSE": (3, 45, 10, 0),       # 09:15-15:30 IST
    "BSE": (3, 45, 10, 0),
    "NASDAQ": (13, 30, 20, 0),   # 09:30-16:00 ET
    "NYSE": (13, 30, 20, 0),
    "LSE": (8, 0, 16, 30),       # 08:00-16:30 UTC
    "HKEX": (1, 30, 8, 0),       # 09:30-16:00 HKT
    "TSE": (0, 0, 6, 30),        # 09:00-15:30 JST
    "ASX": (23, 0, 5, 0),        # 10:00-16:00 AEST (prev day UTC)
}


def _exchange_from_internal_symbol(symbol: str) -> str:
    """Extract exchange from internal symbol format (e.g. 'RELIANCE.NSE' -> 'NSE').

    Falls back to 'CRYPTO' for dash-notation symbols (e.g. 'BTC-USD')
    and 'NASDAQ' for bare symbols.
    """
    parts = symbol.rsplit(".", 1)
    if len(parts) == 2:
        return parts[1].upper()
    if "-" in symbol:
        return "CRYPTO"
    return "NASDAQ"


def _is_market_open(symbol: str, now_utc: datetime | None = None) -> bool:
    """Return True if the exchange for *symbol* is currently trading.

    Falls back to True (poll anyway) if exchange hours are unknown,
    so new symbols are never silently skipped.
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)

    exchange = _exchange_from_internal_symbol(symbol)
    hours = _EXCHANGE_UTC_HOURS.get(exchange)
    if hours is None:
        return True  # Unknown exchange -- poll anyway

    open_h, open_m, close_h, close_m = hours
    now_min = now_utc.hour * 60 + now_utc.minute
    open_min = open_h * 60 + open_m
    close_min = close_h * 60 + close_m

    # Handle midnight-crossing exchanges (e.g. ASX)
    if open_min > close_min:
        return now_min >= open_min or now_min < close_min
    return open_min <= now_min < close_min


def _currency_for_exchange(exchange: str) -> str:
    _map = {
        "NSE": "INR",
        "BSE": "INR",
        "CRYPTO": "USD",
        "NASDAQ": "USD",
        "NYSE": "USD",
        "LSE": "GBP",
    }
    return _map.get(exchange, "USD")


class YahooFeed(BaseFeed):
    """Polls Yahoo Finance for historical OHLCV bars.

    Not a real-time streaming feed -- callers should use ``poll_ohlcv`` on a
    schedule or at startup to seed the database.
    """

    def __init__(self) -> None:
        super().__init__(name="yahoo")
        self._symbols: list[str] = []
        self._poll_task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # BaseFeed interface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        logger.info("yahoo_feed.connect")
        self._is_connected = True

    async def disconnect(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._is_connected = False
        logger.info("yahoo_feed.disconnect")

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)
        logger.info("yahoo_feed.subscribe", symbols=self._symbols)

    async def start(self) -> None:
        """Start a background polling loop that fetches 1-min bars every 30s."""
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    async def fetch_latest(self, symbol: str) -> list[NormalizedOHLCV]:
        """Fetch the latest 1-min bars for *symbol*. Alias used by the ingestion worker."""
        bars = await self.poll_ohlcv(symbol, period="1d", interval="1m")
        for bar in bars:
            await self._emit_ohlcv(bar)
        return bars

    async def poll_ohlcv(
        self,
        symbol: str,
        period: str = "5d",
        interval: str = "1d",
    ) -> list[NormalizedOHLCV]:
        """Fetch OHLCV history for *symbol* and return normalized bars.

        Runs the blocking ``yfinance`` call in a thread-pool executor so we
        don't block the event-loop.
        """
        loop = asyncio.get_running_loop()
        bars = await loop.run_in_executor(None, self._fetch_sync, symbol, period, interval)
        return bars

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------
    def _fetch_sync(
        self, symbol: str, period: str, interval: str
    ) -> list[NormalizedOHLCV]:
        """Blocking yfinance download -- called via executor."""
        yf_symbol = self._to_yf_ticker(symbol)
        exchange = _exchange_for_symbol(yf_symbol)
        currency = _currency_for_exchange(exchange)

        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=period, interval=interval)
        except Exception:
            logger.exception("yahoo_feed.fetch_error", symbol=symbol)
            return []

        if df is None or df.empty:
            return []

        bars: list[NormalizedOHLCV] = []
        for ts, row in df.iterrows():
            bar = NormalizedOHLCV(
                symbol=self._canonical_symbol(symbol),
                exchange=exchange,
                timestamp=ts.to_pydatetime().replace(tzinfo=UTC),
                timeframe=interval,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row.get("Volume", 0)),
                currency=currency,
            )
            bars.append(bar)

        logger.info("yahoo_feed.fetched", symbol=symbol, bars=len(bars))
        return bars

    async def _poll_loop(self) -> None:
        """Periodically polls 1-min OHLCV data and emits bars via callbacks.

        Skips symbols whose exchange is currently closed.
        """
        while self._running:
            for symbol in self._symbols:
                if not _is_market_open(symbol):
                    logger.debug("yahoo_feed.market_closed", symbol=symbol)
                    continue
                try:
                    bars = await self.poll_ohlcv(symbol, period="1d", interval="1m")
                    for bar in bars:
                        await self._emit_ohlcv(bar)
                except Exception:
                    logger.exception("yahoo_feed.poll_error", symbol=symbol)
            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Symbol helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_yf_ticker(symbol: str) -> str:
        """Convert internal symbol to yfinance ticker.

        Internal format: ``RELIANCE.NSE`` -> yfinance ``RELIANCE.NS``
        """
        parts = symbol.rsplit(".", 1)
        if len(parts) == 2:
            name, exch = parts
            _exch_to_suffix = {
                "NSE": ".NS",
                "BSE": ".BO",
                "NASDAQ": "",
                "NYSE": "",
                "CRYPTO": "",
            }
            suffix = _exch_to_suffix.get(exch.upper(), "")
            if exch.upper() == "CRYPTO" or "-" in name:
                return name  # e.g. BTC-USD
            return f"{name}{suffix}"
        return symbol

    @staticmethod
    def _canonical_symbol(symbol: str) -> str:
        """Return the symbol part without exchange suffix."""
        return symbol.rsplit(".", 1)[0]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 9CF1BC92CEB3 - verify with scripts/authorship.py verify
