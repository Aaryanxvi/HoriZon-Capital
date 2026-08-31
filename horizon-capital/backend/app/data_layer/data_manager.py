"""DataManager -- orchestrates data feeds, routes data to KV store and database."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.kv_store import get_kv_store
from app.core.logging import get_logger
from app.data_layer.alpaca_feed import AlpacaFeed
from app.data_layer.crypto_feed import CryptoFeed
from app.data_layer.data_normalizer import NormalizedOHLCV, NormalizedTick
from app.data_layer.polymarket_feed import PolymarketFeed
from app.data_layer.yahoo_feed import YahooFeed


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


logger = get_logger(__name__)


class DataManager:
    """Central hub that wires up feeds, routes ticks to KV store and OHLCV
    bars to the database, and exposes a simple ``get_quote`` read path.
    """

    def __init__(self) -> None:
        self.yahoo_feed = YahooFeed()
        self.alpaca_feed = AlpacaFeed()
        self.crypto_feed = CryptoFeed()
        self.polymarket_feed = PolymarketFeed()

        self._feeds = [
            self.yahoo_feed,
            self.alpaca_feed,
            self.crypto_feed,
            self.polymarket_feed,
        ]

    async def start_all(self) -> None:
        """Connect, subscribe, register callbacks, and start every feed."""
        from app.config import settings
        logger.info("data_manager.start_all")

        us_symbols = [s.strip() for s in settings.us_symbols.split(",") if s.strip()]
        crypto_symbols = [s.strip() for s in settings.crypto_symbols.split(",") if s.strip()]
        all_symbols = [s.strip() for s in settings.all_symbols if s.strip()]

        if settings.crypto_discovery_enabled:
            from app.data_layer.crypto_universe import refresh_crypto_universe

            for sym in await refresh_crypto_universe():
                if sym not in crypto_symbols:
                    crypto_symbols.append(sym)

        for feed in self._feeds:
            feed.on_tick(self._handle_tick)
            feed.on_ohlcv(self._handle_ohlcv)

        await self.yahoo_feed.connect()
        await self.yahoo_feed.subscribe(all_symbols)
        await self.yahoo_feed.start()

        await self.alpaca_feed.connect()
        await self.alpaca_feed.subscribe(us_symbols)
        await self.alpaca_feed.start()

        await self.crypto_feed.connect()
        await self.crypto_feed.subscribe(crypto_symbols)
        await self.crypto_feed.start()

        await self.polymarket_feed.connect()
        await self.polymarket_feed.subscribe([])
        await self.polymarket_feed.start()

        logger.info("data_manager.all_feeds_started")

    async def stop_all(self) -> None:
        """Gracefully shut down every feed."""
        logger.info("data_manager.stop_all")
        for feed in self._feeds:
            try:
                await feed.disconnect()
            except Exception:
                logger.exception("data_manager.disconnect_error", feed=feed.name)
        logger.info("data_manager.all_feeds_stopped")

    async def _handle_tick(self, tick: NormalizedTick) -> None:
        """Store latest quote in KV store and publish on a channel."""
        redis_key = f"horizon:quote:{tick.symbol}"
        try:
            kv = get_kv_store()
            await kv.hset(redis_key, mapping=tick.to_redis_dict())
            await kv.expire(redis_key, 3600)
            # Also mirror to the price key everything else reads (REPL, position
            # marking). Tick-only feeds — Polymarket — never emit OHLCV, so
            # without this their symbols showed no price at all.
            if tick.last_price and tick.last_price > 0:
                await kv.set(f"horizon:price:{tick.symbol}", str(tick.last_price))
                await kv.set(
                    f"horizon:price:{tick.symbol}:ts", datetime.now(UTC).isoformat()
                )
            channel = f"horizon.market.{tick.exchange}.{tick.symbol}"
            await kv.publish(channel, json.dumps(tick.to_redis_dict()))
        except Exception:
            logger.warning("data_manager.tick_write_error", symbol=tick.symbol)

    async def _handle_ohlcv(self, bar: NormalizedOHLCV) -> None:
        """Upsert OHLCV bar into the database and cache latest price in KV."""
        try:
            kv = get_kv_store()
            price_str = str(bar.close)
            ts_str = datetime.now(UTC).isoformat()
            await kv.set(f"horizon:price:{bar.symbol}", price_str)
            await kv.set(f"horizon:price:{bar.symbol}:ts", ts_str)
            if bar.exchange and bar.exchange != "UNKNOWN":
                await kv.set(f"horizon:price:{bar.symbol}.{bar.exchange}", price_str)
                await kv.set(f"horizon:price:{bar.symbol}.{bar.exchange}:ts", ts_str)
        except Exception:
            logger.warning("data_manager.price_cache_error", symbol=bar.symbol)

        try:
            async with _get_session_factory()() as session:
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
            logger.warning(
                "data_manager.ohlcv_write_error",
                symbol=bar.symbol,
                timeframe=bar.timeframe,
            )

    async def get_quote(self, symbol: str) -> NormalizedTick | None:
        """Return the latest cached tick for *symbol* from KV store."""
        redis_key = f"horizon:quote:{symbol}"
        data = await get_kv_store().hgetall(redis_key)
        if not data:
            return None
        try:
            return NormalizedTick.from_redis_dict(data)
        except Exception:
            logger.exception("data_manager.get_quote_parse_error", symbol=symbol)
            return None
