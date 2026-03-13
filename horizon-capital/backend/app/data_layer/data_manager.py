"""DataManager -- orchestrates all feeds, routes data to Redis & Postgres."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis_client import redis_client
from app.data_layer.alpaca_feed import AlpacaFeed
from app.data_layer.crypto_feed import CryptoFeed
from app.data_layer.data_normalizer import NormalizedOHLCV, NormalizedTick
from app.data_layer.forex_feed import ForexFeed
from app.data_layer.polygon_feed import PolygonFeed
from app.data_layer.yahoo_feed import YahooFeed
from app.data_layer.zerodha_feed import ZerodhaFeed
from app.models.market_data import OHLCV

logger = get_logger(__name__)


class DataManager:
    """Central hub that wires up every feed, routes ticks to Redis and OHLCV
    bars to Postgres, and exposes a simple ``get_quote`` read path.
    """

    def __init__(self) -> None:
        # Feeds
        self.yahoo_feed = YahooFeed()
        self.alpaca_feed = AlpacaFeed()
        self.zerodha_feed = ZerodhaFeed()
        self.crypto_feed = CryptoFeed()
        self.forex_feed = ForexFeed()
        self.polygon_feed = PolygonFeed()

        self._feeds = [
            self.yahoo_feed,
            self.alpaca_feed,
            self.zerodha_feed,
            self.crypto_feed,
            self.polygon_feed,
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start_all(self) -> None:
        """Connect, subscribe, register callbacks, and start every feed."""
        logger.info("data_manager.start_all")

        # Parse symbol lists from settings
        india_symbols = [s.strip() for s in settings.india_symbols.split(",") if s.strip()]
        us_symbols = [s.strip() for s in settings.us_symbols.split(",") if s.strip()]
        crypto_symbols = [s.strip() for s in settings.crypto_symbols.split(",") if s.strip()]

        # Register callbacks on every BaseFeed
        for feed in self._feeds:
            feed.on_tick(self._handle_tick)
            feed.on_ohlcv(self._handle_ohlcv)

        # -- Yahoo (all symbols, for historical back-fill) --------
        await self.yahoo_feed.connect()
        all_yf_symbols = india_symbols + us_symbols + crypto_symbols
        await self.yahoo_feed.subscribe(all_yf_symbols)
        await self.yahoo_feed.start()

        # -- Zerodha (Indian symbols) ----------------------------
        await self.zerodha_feed.connect()
        await self.zerodha_feed.subscribe(india_symbols)
        await self.zerodha_feed.start()

        # -- Alpaca (US symbols) ----------------------------------
        await self.alpaca_feed.connect()
        await self.alpaca_feed.subscribe(us_symbols)
        await self.alpaca_feed.start()

        # -- Crypto -----------------------------------------------
        await self.crypto_feed.connect()
        await self.crypto_feed.subscribe(crypto_symbols)
        await self.crypto_feed.start()

        # -- Polygon (US symbols, if key set) ---------------------
        await self.polygon_feed.connect()
        await self.polygon_feed.subscribe(us_symbols)
        await self.polygon_feed.start()

        # -- Forex (standalone, no BaseFeed) ----------------------
        await self.forex_feed.start()

        logger.info("data_manager.all_feeds_started")

    async def stop_all(self) -> None:
        """Gracefully shut down every feed."""
        logger.info("data_manager.stop_all")
        for feed in self._feeds:
            try:
                await feed.disconnect()
            except Exception:
                logger.exception("data_manager.disconnect_error", feed=feed.name)
        await self.forex_feed.stop()
        logger.info("data_manager.all_feeds_stopped")

    # ------------------------------------------------------------------
    # Tick handling -> Redis
    # ------------------------------------------------------------------
    async def _handle_tick(self, tick: NormalizedTick) -> None:
        """Store latest quote in Redis HSET and publish on a channel."""
        redis_key = f"horizon:quote:{tick.symbol}"
        try:
            await redis_client.hset(redis_key, mapping=tick.to_redis_dict())
            # Set a TTL so stale quotes auto-expire after 1 hour
            await redis_client.expire(redis_key, 3600)

            # Publish for real-time subscribers
            channel = f"horizon.market.{tick.exchange}.{tick.symbol}"
            await redis_client.publish(channel, json.dumps(tick.to_redis_dict()))
        except Exception:
            logger.exception("data_manager.tick_redis_error", symbol=tick.symbol)

    # ------------------------------------------------------------------
    # OHLCV handling -> Postgres
    # ------------------------------------------------------------------
    async def _handle_ohlcv(self, bar: NormalizedOHLCV) -> None:
        """Upsert OHLCV bar into Postgres via async session."""
        try:
            async with async_session_factory() as session:
                # Use raw SQL upsert to handle the unique constraint gracefully
                stmt = text(
                    """
                    INSERT INTO ohlcv (symbol, exchange, timestamp, timeframe,
                                       open, high, low, close, volume, open_interest)
                    VALUES (:symbol, :exchange, :timestamp, :timeframe,
                            :open, :high, :low, :close, :volume, :open_interest)
                    ON CONFLICT (symbol, exchange, timestamp, timeframe)
                    DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low  = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        open_interest = EXCLUDED.open_interest
                    """
                )
                await session.execute(
                    stmt,
                    {
                        "symbol": bar.symbol,
                        "exchange": bar.exchange,
                        "timestamp": bar.timestamp,
                        "timeframe": bar.timeframe,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "open_interest": bar.open_interest,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception(
                "data_manager.ohlcv_postgres_error",
                symbol=bar.symbol,
                timeframe=bar.timeframe,
            )

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------
    async def get_quote(self, symbol: str) -> NormalizedTick | None:
        """Return the latest cached tick for *symbol* from Redis."""
        redis_key = f"horizon:quote:{symbol}"
        data = await redis_client.hgetall(redis_key)
        if not data:
            return None
        try:
            return NormalizedTick.from_redis_dict(data)
        except Exception:
            logger.exception("data_manager.get_quote_parse_error", symbol=symbol)
            return None

    async def get_forex_rate(self) -> float | None:
        """Convenience proxy for the forex feed."""
        return await self.forex_feed.get_rate()
