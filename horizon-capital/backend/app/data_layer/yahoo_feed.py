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

import pandas as pd
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
        self._last_emitted: dict[str, datetime] = {}

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

        bars = self._to_bars(symbol, df, interval, exchange, currency)
        logger.info("yahoo_feed.fetched", symbol=symbol, bars=len(bars))
        return bars

    def _to_bars(
        self, symbol: str, df, interval: str, exchange: str, currency: str
    ) -> list[NormalizedOHLCV]:
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
                volume=int(row.get("Volume", 0) or 0),
                currency=currency,
            )
            bars.append(bar)
        return bars

    def _download_batch_sync(self, symbols: list[str]) -> dict[str, list[NormalizedOHLCV]]:
        """Today's 1-min bars for every symbol in ONE yfinance call (executor)."""
        yf_map = {self._to_yf_ticker(s): s for s in symbols}
        try:
            df = yf.download(
                list(yf_map), period="1d", interval="1m", group_by="ticker",
                auto_adjust=False, progress=False, threads=True,
            )
        except Exception:
            logger.exception("yahoo_feed.batch_error", n=len(symbols))
            return {}
        if df is None or df.empty:
            return {}

        multi = isinstance(df.columns, pd.MultiIndex)
        present = set(df.columns.get_level_values(0)) if multi else set()
        out: dict[str, list[NormalizedOHLCV]] = {}
        for yf_symbol, symbol in yf_map.items():
            if multi and yf_symbol not in present:
                continue
            if not multi and len(yf_map) > 1:
                break
            sub = (df[yf_symbol] if multi else df).dropna(subset=["Close"])
            exchange = _exchange_for_symbol(yf_symbol)
            out[symbol] = self._to_bars(
                symbol, sub, "1m", exchange, _currency_for_exchange(exchange)
            )
        return out

    async def fetch_latest_batch(self, symbols: list[str]) -> dict[str, float]:
        """Latest 1-min bars for many symbols at once; returns ``{symbol: last close}``.

        One yfinance call per cycle instead of one per symbol (yfinance still
        fans out per-ticker HTTP requests, but on parallel threads). Only bars
        at or after the last one emitted are re-emitted -- the in-progress
        minute keeps updating without re-upserting the whole session each poll.
        """
        if not symbols:
            return {}
        loop = asyncio.get_running_loop()
        batch = await loop.run_in_executor(None, self._download_batch_sync, list(symbols))
        prices: dict[str, float] = {}
        for symbol, bars in batch.items():
            last = self._last_emitted.get(symbol)
            for bar in bars:
                if last is None or bar.timestamp >= last:
                    await self._emit_ohlcv(bar)
            if bars:
                self._last_emitted[symbol] = bars[-1].timestamp
                prices[symbol] = bars[-1].close
        return prices

    async def _poll_loop(self) -> None:
        """Periodically polls 1-min OHLCV data and emits bars via callbacks.

        Skips symbols whose exchange is currently closed; everything open is
        fetched in one batched download.
        """
        while self._running:
            open_now = [s for s in self._symbols if _is_market_open(s)]
            try:
                await self.fetch_latest_batch(open_now)
            except Exception:
                logger.exception("yahoo_feed.poll_error", n=len(open_now))
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
