"""DataIngestionWorker -- starts data feeds, polls EOD data, and handles backfill."""

from __future__ import annotations

import asyncio
from datetime import UTC

from sqlalchemy import text

from app.agents.front_office.portfolio.currency import FOREX_KEY
from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger
from app.data_layer.data_manager import DataManager


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("worker.data_ingestion")

YAHOO_POLL_INTERVAL = 30
COINGECKO_POLL_INTERVAL = 60
FOREX_POLL_INTERVAL = 3600  # USD/INR moves slowly; hourly is plenty
RECONNECT_DELAY = 10
MAX_RECONNECT_ATTEMPTS = 5
FETCH_TIMEOUT = 30.0


class DataIngestionWorker:
    """Orchestrates market data ingestion.

    Responsibilities:
    - Start and maintain data feeds via DataManager.
    - Poll Yahoo Finance every 30 s for 1-min bar data.
    - Poll CoinGecko every 60 s for crypto prices.
    - On startup, check whether OHLCV data exists; if not, trigger a historical backfill.
    """

    def __init__(self) -> None:
        self.data_manager = DataManager()
        self._running: bool = False
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        """Entry point: check backfill, start feeds, launch periodic tasks."""
        self._running = True
        logger.info("data_ingestion_worker.starting")

        await self._check_backfill()
        await self._start_feeds_with_reconnect()

        self._tasks = [
            asyncio.create_task(self._poll_yahoo_eod()),
            asyncio.create_task(self._poll_coingecko()),
            asyncio.create_task(self._poll_forex()),
        ]

        logger.info("data_ingestion_worker.started")

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("data_ingestion_worker.stopping")
        self._running = False

        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self.data_manager.stop_all()
        logger.info("data_ingestion_worker.stopped")

    async def _start_feeds_with_reconnect(self) -> None:
        """Start all feeds via DataManager, retrying on failure."""
        attempt = 0
        while self._running and attempt < MAX_RECONNECT_ATTEMPTS:
            try:
                await self.data_manager.start_all()
                logger.info("data_ingestion_worker.feeds_connected")
                return
            except Exception as exc:
                attempt += 1
                logger.error(
                    "data_ingestion_worker.feed_connect_error",
                    attempt=attempt,
                    max_attempts=MAX_RECONNECT_ATTEMPTS,
                    error=str(exc),
                )
                if attempt < MAX_RECONNECT_ATTEMPTS:
                    await asyncio.sleep(RECONNECT_DELAY * attempt)

        logger.error("data_ingestion_worker.feeds_failed_all_retries")

    async def _publish_price_update(self, symbol: str, price: float) -> None:
        """Publish a TICK message for the dashboard watchlist."""
        from app.core.messaging import AgentMessage, MessageType
        from app.core.runtime import get_bus

        kv = get_kv_store()
        prev_str = await kv.get(f"horizon:price:prev_close:{symbol}")
        prev_close = float(prev_str) if prev_str else price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

        bus = get_bus()
        await bus.publish(
            AgentMessage(
                sender_id="data-ingestion-worker",
                channel=f"horizon.tick.{symbol}",
                message_type=MessageType.TICK,
                payload={
                    "symbol": symbol,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                    "prev_close": prev_close,
                },
            )
        )

    async def _poll_yahoo_eod(self) -> None:
        """Poll Yahoo Finance every 30 s for 1-min OHLCV data."""
        try:
            while self._running:
                try:
                    symbols = settings.all_symbols
                    logger.debug("polling_yahoo_eod", symbols_count=len(symbols))

                    kv = get_kv_store()
                    for symbol in symbols:
                        prev_key = f"horizon:price:prev_close:{symbol}"
                        existing = await kv.get(prev_key)
                        if not existing:
                            current = await kv.get(f"horizon:price:{symbol}")
                            if current:
                                await kv.set(prev_key, current)

                    for symbol in symbols:
                        try:
                            await asyncio.wait_for(
                                self.data_manager.yahoo_feed.fetch_latest(symbol),
                                timeout=FETCH_TIMEOUT,
                            )
                            try:
                                price_str = await kv.get(f"horizon:price:{symbol}")
                                if price_str:
                                    await self._publish_price_update(symbol, float(price_str))
                            except Exception:
                                pass
                        except TimeoutError:
                            logger.warning("yahoo_fetch_timeout", symbol=symbol)
                        except Exception as exc:
                            logger.warning(
                                "yahoo_eod_fetch_error",
                                symbol=symbol,
                                error=str(exc),
                            )

                except Exception as exc:
                    logger.error("yahoo_eod_poll_error", error=str(exc))

                await asyncio.sleep(YAHOO_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _poll_coingecko(self) -> None:
        """Poll CoinGecko every 60 s for crypto price data."""
        try:
            while self._running:
                try:
                    crypto_symbols = [
                        s.strip()
                        for s in settings.crypto_symbols.split(",")
                        if s.strip()
                    ]
                    logger.debug("polling_coingecko", symbols=crypto_symbols)

                    kv = get_kv_store()
                    for symbol in crypto_symbols:
                        try:
                            await asyncio.wait_for(
                                self.data_manager.crypto_feed.fetch_latest(symbol),
                                timeout=FETCH_TIMEOUT,
                            )
                            try:
                                raw = symbol.lower().split("-")[0]
                                price_str = await kv.get(
                                    f"horizon:price:{raw}"
                                ) or await kv.get(f"horizon:price:{symbol}")
                                if price_str:
                                    await self._publish_price_update(symbol, float(price_str))
                            except Exception:
                                pass
                        except TimeoutError:
                            logger.warning("crypto_fetch_timeout", symbol=symbol)
                        except Exception as exc:
                            logger.warning(
                                "coingecko_fetch_error",
                                symbol=symbol,
                                error=str(exc),
                            )

                except Exception as exc:
                    logger.error("coingecko_poll_error", error=str(exc))

                await asyncio.sleep(COINGECKO_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _fetch_forex_once(self) -> None:
        """Fetch USD/INR from yfinance and write it to KV, if valid."""
        import yfinance as yf

        hist = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yf.Ticker("USDINR=X").history(period="1d")
        )
        if hist.empty:
            return

        rate = float(hist["Close"].iloc[-1])
        if rate > 0:
            await get_kv_store().set(FOREX_KEY, str(rate))
            logger.info("forex_rate_updated", usdinr=round(rate, 4))

    async def _poll_forex(self) -> None:
        """Poll USD/INR hourly; fetch immediately so the reader has a rate at boot."""
        try:
            while self._running:
                try:
                    await self._fetch_forex_once()
                except Exception as exc:
                    logger.warning("forex_poll_error", error=str(exc))

                await asyncio.sleep(FOREX_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _check_backfill(self) -> None:
        """On startup, if no OHLCV data exists trigger a historical backfill."""
        try:
            async with _get_session_factory()() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) AS cnt FROM ohlcv")
                )
                row = result.fetchone()
                count = row.cnt if row else 0

            if count == 0:
                logger.warning("data_ingestion_worker.no_ohlcv_data_found_triggering_backfill")
                await self._trigger_backfill()
            else:
                logger.info(
                    "data_ingestion_worker.ohlcv_data_exists",
                    row_count=count,
                )
        except Exception as exc:
            logger.error("data_ingestion_worker.backfill_check_error", error=str(exc))

    async def _trigger_backfill(self) -> None:
        """Use Yahoo Finance to backfill 5 years of daily OHLCV for all symbols."""
        try:
            import yfinance as yf

            from app.data_layer.data_normalizer import NormalizedOHLCV

            symbols = settings.all_symbols
            logger.info("backfill_starting", symbols_count=len(symbols))

            for symbol in symbols:
                try:
                    yf_symbol = self._to_yfinance_symbol(symbol)
                    logger.info("backfilling_symbol", symbol=symbol, yf_symbol=yf_symbol)

                    ticker = yf.Ticker(yf_symbol)
                    hist = ticker.history(period="5y", interval="1d")

                    if hist.empty:
                        logger.warning("backfill_no_data", symbol=symbol)
                        continue

                    exchange = self._extract_exchange(symbol)

                    for ts, row in hist.iterrows():
                        bar = NormalizedOHLCV(
                            symbol=symbol.split(".")[0],
                            exchange=exchange,
                            timestamp=ts.to_pydatetime().replace(tzinfo=UTC),
                            timeframe="1d",
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=int(row["Volume"]),
                        )
                        await self.data_manager._handle_ohlcv(bar)

                    logger.info(
                        "backfill_symbol_complete",
                        symbol=symbol,
                        rows=len(hist),
                    )

                except Exception as exc:
                    logger.error(
                        "backfill_symbol_error",
                        symbol=symbol,
                        error=str(exc),
                    )

            logger.info("backfill_complete")

        except ImportError:
            logger.error("backfill_yfinance_not_installed")
        except Exception as exc:
            logger.error("backfill_error", error=str(exc))

    @staticmethod
    def _to_yfinance_symbol(symbol: str) -> str:
        """Convert canonical symbol (e.g. RELIANCE.NSE) to yfinance format."""
        mapping = {
            "NSE": ".NS",
            "BSE": ".BO",
            "NASDAQ": "",
            "NYSE": "",
        }
        parts = symbol.split(".")
        if len(parts) == 2:
            name, exchange = parts
            suffix = mapping.get(exchange, "")
            return f"{name}{suffix}"
        return symbol

    @staticmethod
    def _extract_exchange(symbol: str) -> str:
        """Extract exchange from canonical symbol."""
        parts = symbol.split(".")
        if len(parts) == 2:
            return parts[1]
        if "-" in symbol:
            return "CRYPTO"
        return "UNKNOWN"
