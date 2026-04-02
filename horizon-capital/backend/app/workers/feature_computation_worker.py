"""FeatureComputationWorker -- listens for new OHLCV data and computes technical indicators."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()

logger = get_logger("worker.feature_computation")

# Minimum bars required to compute all indicators
MIN_BARS_REQUIRED = 50


class TechnicalIndicators:
    """Compute 23 technical indicators on an OHLCV DataFrame.

    Expected DataFrame columns: open, high, low, close, volume.
    All methods return the DataFrame with new columns added in-place.
    """

    @staticmethod
    def sma(df: pd.DataFrame, period: int = 20, column: str = "close") -> pd.DataFrame:
        """Simple Moving Average."""
        df[f"sma_{period}"] = df[column].rolling(window=period).mean()
        return df

    @staticmethod
    def ema(df: pd.DataFrame, period: int = 20, column: str = "close") -> pd.DataFrame:
        """Exponential Moving Average."""
        df[f"ema_{period}"] = df[column].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.DataFrame:
        """Relative Strength Index."""
        delta = df[column].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        column: str = "close",
    ) -> pd.DataFrame:
        """MACD, signal line, and histogram."""
        ema_fast = df[column].ewm(span=fast, adjust=False).mean()
        ema_slow = df[column].ewm(span=slow, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        return df

    @staticmethod
    def bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0,
        column: str = "close",
    ) -> pd.DataFrame:
        """Bollinger Bands (upper, middle, lower)."""
        sma = df[column].rolling(window=period).mean()
        std = df[column].rolling(window=period).std()
        df["bb_upper"] = sma + (std_dev * std)
        df["bb_middle"] = sma
        df["bb_lower"] = sma - (std_dev * std)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        return df

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Average True Range."""
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - df["close"].shift(1)).abs()
        low_prev_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(window=period).mean()
        return df

    @staticmethod
    def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        """Stochastic Oscillator (%K and %D)."""
        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()
        df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
        return df

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Average Directional Index."""
        plus_dm = df["high"].diff()
        minus_dm = -df["low"].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr_high_low = df["high"] - df["low"]
        tr_high_close = (df["high"] - df["close"].shift(1)).abs()
        tr_low_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([tr_high_low, tr_high_close, tr_low_close], axis=1).max(axis=1)

        atr = true_range.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr.replace(0, np.nan))

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        df["adx"] = dx.rolling(window=period).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        return df

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.DataFrame:
        """On-Balance Volume."""
        direction = np.where(df["close"] > df["close"].shift(1), 1, -1)
        direction = np.where(df["close"] == df["close"].shift(1), 0, direction)
        df["obv"] = (df["volume"] * direction).cumsum()
        return df

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.DataFrame:
        """Volume Weighted Average Price (cumulative intraday proxy)."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_tp_vol = (typical_price * df["volume"]).cumsum()
        cumulative_vol = df["volume"].cumsum()
        df["vwap"] = cumulative_tp_vol / cumulative_vol.replace(0, np.nan)
        return df

    @classmethod
    def compute_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all 23 technical indicators and return the enriched DataFrame.

        Indicators computed:
        1-2. SMA(20), SMA(50)
        3-4. EMA(12), EMA(26)
        5. RSI(14)
        6-8. MACD, MACD Signal, MACD Histogram
        9-12. BB Upper, BB Middle, BB Lower, BB Width
        13. ATR(14)
        14-15. Stochastic %K, %D
        16-18. ADX, +DI, -DI
        19. OBV
        20. VWAP
        21-23. SMA(200), EMA(50), EMA(200)
        """
        df = cls.sma(df, period=20)
        df = cls.sma(df, period=50)
        df = cls.sma(df, period=200)
        df = cls.ema(df, period=12)
        df = cls.ema(df, period=26)
        df = cls.ema(df, period=50)
        df = cls.ema(df, period=200)
        df = cls.rsi(df, period=14)
        df = cls.macd(df)
        df = cls.bollinger_bands(df)
        df = cls.atr(df)
        df = cls.stochastic(df)
        df = cls.adx(df)
        df = cls.obv(df)
        df = cls.vwap(df)
        return df


class VolatilityFeatures:
    """Compute volatility-specific features on an OHLCV DataFrame."""

    @staticmethod
    def realized_volatility(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """Annualized realized volatility from log returns."""
        log_returns = np.log(df["close"] / df["close"].shift(1))
        df["realized_vol"] = log_returns.rolling(window=window).std() * np.sqrt(252)
        return df

    @staticmethod
    def parkinson_volatility(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """Parkinson high-low volatility estimator."""
        log_hl = np.log(df["high"] / df["low"])
        df["parkinson_vol"] = (
            np.sqrt(log_hl.pow(2).rolling(window=window).mean() / (4 * np.log(2))) * np.sqrt(252)
        )
        return df

    @staticmethod
    def garman_klass_volatility(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
        """Garman-Klass volatility estimator."""
        log_hl = np.log(df["high"] / df["low"])
        log_co = np.log(df["close"] / df["open"])
        gk = 0.5 * log_hl.pow(2) - (2 * np.log(2) - 1) * log_co.pow(2)
        df["garman_klass_vol"] = np.sqrt(gk.rolling(window=window).mean() * 252)
        return df

    @classmethod
    def compute_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all volatility features."""
        df = cls.realized_volatility(df)
        df = cls.parkinson_volatility(df)
        df = cls.garman_klass_volatility(df)
        return df


class FeatureStore:
    """Persist computed features in Redis (cache) and Postgres (durable storage)."""

    @staticmethod
    async def store_features(
        symbol: str,
        exchange: str,
        timeframe: str,
        features: dict[str, float],
        timestamp: datetime,
    ) -> None:
        """Store feature vector in Redis hash and Postgres."""
        redis_key = f"horizon:features:{symbol}:{timeframe}"

        # Redis cache
        redis_data = {k: str(v) for k, v in features.items() if pd.notna(v)}
        redis_data["timestamp"] = timestamp.isoformat()
        redis_data["symbol"] = symbol
        redis_data["timeframe"] = timeframe

        kv = get_kv_store()
        await kv.hset(redis_key, mapping=redis_data)
        await kv.expire(redis_key, 7200)  # 2-hour TTL

        # Postgres persistence
        try:
            import orjson

            features_json = orjson.dumps(
                {k: v for k, v in features.items() if pd.notna(v)},
                default=str,
            ).decode()

            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO feature_snapshots
                            (id, symbol, exchange, timeframe,
                             features, computed_at, created_at, updated_at)
                        VALUES
                            (:id, :symbol, :exchange, :timeframe,
                             :features, :computed_at, :now, :now)
                        ON CONFLICT (symbol, exchange, timeframe) DO UPDATE
                        SET features = excluded.features, updated_at = excluded.updated_at
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "symbol": symbol,
                        "exchange": exchange,
                        "timeframe": timeframe,
                        "features": features_json,
                        "computed_at": timestamp,
                        "now": datetime.now(UTC),
                    },
                )
                await session.commit()
        except Exception as exc:
            # Log but don't fail -- Redis cache is the primary fast path
            logger.warning("feature_store_postgres_error", symbol=symbol, error=str(exc))

    @staticmethod
    async def get_features(symbol: str, timeframe: str = "1d") -> dict[str, str] | None:
        """Read latest features from Redis cache."""
        redis_key = f"horizon:features:{symbol}:{timeframe}"
        data = await get_kv_store().hgetall(redis_key)
        return data if data else None


class FeatureComputationWorker:
    """Listens for new OHLCV data and computes technical + volatility features.

    The worker subscribes to ``horizon.data.*`` channels via Redis pub/sub.
    When new data arrives it loads the latest OHLCV bars from Postgres,
    computes all 23 technical indicators plus volatility features, stores
    the result in the FeatureStore, and publishes on
    ``horizon.features.{symbol}.{timeframe}``.
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._poll_task: asyncio.Task | None = None
        self.feature_store = FeatureStore()

    async def run(self) -> None:
        """Periodically recompute features for all symbols."""
        self._running = True
        logger.info("feature_computation_worker.starting")

        # Initial computation on startup
        await self._compute_all_symbols()

        self._poll_task = asyncio.create_task(self._periodic_recompute())
        logger.info("feature_computation_worker.started")

        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("feature_computation_worker.stopping")
        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        logger.info("feature_computation_worker.stopped")

    async def _periodic_recompute(self) -> None:
        """Recompute features for all symbols every 2 minutes as a safety net."""
        try:
            while self._running:
                await asyncio.sleep(120)
                await self._compute_all_symbols()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Feature computation
    # ------------------------------------------------------------------

    async def _compute_all_symbols(self) -> None:
        """Compute features for every tracked symbol."""
        symbols = settings.all_symbols
        for symbol in symbols:
            try:
                await self._compute_features_for_symbol(symbol)
            except Exception as exc:
                logger.error(
                    "feature_computation_error",
                    symbol=symbol,
                    error=str(exc),
                )

    async def _compute_features_for_symbol(
        self, symbol: str, timeframe: str = "1d"
    ) -> None:
        """Load OHLCV, compute indicators, store and publish."""
        # Strip exchange suffix for DB query
        raw_symbol = symbol.split(".")[0] if "." in symbol else symbol

        # Load OHLCV from Postgres
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    """
                    SELECT timestamp, open, high, low, close, volume, exchange
                    FROM ohlcv
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    ORDER BY timestamp ASC
                    LIMIT 500
                    """
                ),
                {"symbol": raw_symbol, "timeframe": timeframe},
            )
            rows = result.fetchall()

        if len(rows) < MIN_BARS_REQUIRED:
            logger.debug(
                "insufficient_bars_for_features",
                symbol=raw_symbol,
                bars=len(rows),
                required=MIN_BARS_REQUIRED,
            )
            return

        # Build DataFrame
        df = pd.DataFrame(
            [
                {
                    "timestamp": r.timestamp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )
        df = df.set_index("timestamp").sort_index()
        exchange = rows[-1].exchange

        # Compute all indicators
        df = TechnicalIndicators.compute_all(df)
        df = VolatilityFeatures.compute_all(df)

        # Extract the latest row as feature dict
        latest = df.iloc[-1]
        feature_columns = [
            "sma_20", "sma_50", "sma_200",
            "ema_12", "ema_26", "ema_50", "ema_200",
            "rsi",
            "macd", "macd_signal", "macd_histogram",
            "bb_upper", "bb_middle", "bb_lower", "bb_width",
            "atr",
            "stoch_k", "stoch_d",
            "adx", "plus_di", "minus_di",
            "obv", "vwap",
            "realized_vol", "parkinson_vol", "garman_klass_vol",
        ]

        features: dict[str, float] = {}
        for col in feature_columns:
            if col in latest.index:
                val = latest[col]
                if pd.notna(val):
                    features[col] = float(val)

        now = datetime.now(UTC)

        # Store in FeatureStore
        await self.feature_store.store_features(
            symbol=raw_symbol,
            exchange=exchange,
            timeframe=timeframe,
            features=features,
            timestamp=now,
        )

        # Cache notification (no-op in LOCAL mode; Redis pub/sub in PROD mode)
        await get_kv_store().set(
            f"horizon:features:{raw_symbol}:{timeframe}:updated",
            now.isoformat(),
        )

        logger.debug(
            "features_computed",
            symbol=raw_symbol,
            timeframe=timeframe,
            feature_count=len(features),
        )
