"""Feature vector construction for the HMM regime model.

Builds a (T, 6) numpy array from OHLCV data suitable for ``HMMRegimeModel.train()``
and ``HMMRegimeModel.predict()``.

Features
--------
1. returns           -- daily log returns
2. rolling_vol_20d   -- 20-day rolling standard deviation of returns
3. rolling_vol_60d   -- 60-day rolling standard deviation of returns
4. vol_of_vol        -- 20-day rolling std of rolling_vol_20d
5. skewness_20d      -- 20-day rolling skewness of returns
6. kurtosis_20d      -- 20-day rolling kurtosis of returns
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger("features.regime")


class RegimeFeatures:
    """Construct feature vectors for regime detection via HMM."""

    @staticmethod
    def compute(df: pd.DataFrame) -> np.ndarray:
        """Create the feature matrix for HMM input.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain a ``close`` column with price data.

        Returns
        -------
        np.ndarray
            Shape ``(T, 6)`` where ``T`` is the number of valid (non-NaN) rows
            after feature computation.  Rows with any NaN are dropped so the
            HMM receives a clean input.
        """
        close = df["close"]

        # 1. Log returns
        returns = np.log(close / close.shift(1))

        # 2. 20-day rolling volatility
        rolling_vol_20d = returns.rolling(window=20, min_periods=10).std()

        # 3. 60-day rolling volatility
        rolling_vol_60d = returns.rolling(window=60, min_periods=30).std()

        # 4. Volatility of volatility (20-day rolling std of 20d vol)
        vol_of_vol = rolling_vol_20d.rolling(window=20, min_periods=10).std()

        # 5. 20-day rolling skewness
        skewness_20d = returns.rolling(window=20, min_periods=10).skew()

        # 6. 20-day rolling kurtosis
        kurtosis_20d = returns.rolling(window=20, min_periods=10).kurt()

        feature_df = pd.DataFrame(
            {
                "returns": returns,
                "rolling_vol_20d": rolling_vol_20d,
                "rolling_vol_60d": rolling_vol_60d,
                "vol_of_vol": vol_of_vol,
                "skewness_20d": skewness_20d,
                "kurtosis_20d": kurtosis_20d,
            },
            index=df.index,
        )

        # Drop rows with any NaN so HMM receives complete observations
        clean = feature_df.dropna()

        if len(clean) == 0:
            logger.warning("regime_features_empty", original_len=len(df))
            return np.empty((0, 6))

        logger.info(
            "regime_features_computed",
            original_rows=len(df),
            feature_rows=len(clean),
        )

        return clean.values.astype(np.float64)
