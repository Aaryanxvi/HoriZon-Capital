"""Momentum strategy using MACD, RSI, EMA, volume, and VWAP."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "momentum"

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Signal | None:
        if df is None or df.empty:
            return None
        features = df.iloc[-1].to_dict() if isinstance(df, pd.DataFrame) else df
        return self._rule_based(symbol, features)

    def generate_signal_from_features(
        self,
        symbol: str,
        features: dict[str, Any],
    ) -> Signal | None:
        return self._rule_based(symbol, features)

    def _rule_based(self, symbol: str, features: dict[str, Any]) -> Signal | None:
        rsi = features.get("rsi")
        macd = features.get("macd")
        macd_signal = features.get("macd_signal")
        ema_20 = features.get("ema_20")
        close = features.get("close")

        if any(v is None for v in [rsi, macd, macd_signal, ema_20, close]):
            return None

        volume = features.get("volume")
        volume_avg = features.get("volume_avg_20")
        vwap = features.get("vwap")
        atr = features.get("atr")
        atr_avg_20 = features.get("atr_avg_20")

        vpvma_score = self._compute_vpvma(
            macd, macd_signal, volume, volume_avg, atr, atr_avg_20
        )

        indicators: dict[str, float] = {}

        if rsi < 30:
            indicators["rsi"] = (30 - rsi) / 30
        elif rsi > 70:
            indicators["rsi"] = -(rsi - 70) / 30
        else:
            indicators["rsi"] = (rsi - 50) / 50 * 0.3

        macd_spread = macd - macd_signal
        macd_magnitude = abs(macd_spread) / (abs(macd_signal) + 1e-8)
        indicators["macd"] = min(macd_magnitude, 1.0) * (1 if macd_spread > 0 else -1)

        indicators["vpvma"] = vpvma_score

        ema_deviation = (close - ema_20) / ema_20 if ema_20 > 0 else 0.0
        indicators["ema_trend"] = max(-1.0, min(1.0, ema_deviation * 10))

        if volume is not None and volume_avg is not None and volume_avg > 0:
            vol_ratio = volume / volume_avg
            indicators["volume"] = min(vol_ratio - 1.0, 1.0)
        else:
            indicators["volume"] = 0.0

        if vwap is not None and vwap > 0:
            vwap_dev = (close - vwap) / vwap
            indicators["vwap"] = max(-1.0, min(1.0, vwap_dev * 20))
        else:
            indicators["vwap"] = 0.0

        weights = {
            "rsi": 0.20,
            "macd": 0.20,
            "vpvma": 0.20,
            "ema_trend": 0.15,
            "volume": 0.15,
            "vwap": 0.10,
        }

        fusion_score = sum(
            indicators.get(k, 0.0) * w for k, w in weights.items()
        )

        bullish_count = sum(1 for v in indicators.values() if v > 0.1)
        bearish_count = sum(1 for v in indicators.values() if v < -0.1)

        if fusion_score > 0.15 and bullish_count >= 3:
            strength = self._compute_strength_fusion(
                fusion_score, bullish_count, len(indicators)
            )
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"Momentum BUY: fusion={fusion_score:.3f}, "
                    f"{bullish_count}/{len(indicators)} indicators bullish, "
                    f"RSI={rsi:.1f}, MACD spread={macd - macd_signal:.4f}"
                ),
            )

        if fusion_score < -0.15 and bearish_count >= 3:
            strength = self._compute_strength_fusion(
                abs(fusion_score), bearish_count, len(indicators)
            )
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                reasoning=(
                    f"Momentum SELL: fusion={fusion_score:.3f}, "
                    f"{bearish_count}/{len(indicators)} indicators bearish, "
                    f"RSI={rsi:.1f}"
                ),
            )

        return None

    @staticmethod
    def _compute_vpvma(
        macd: float,
        macd_signal: float,
        volume: float | None,
        volume_avg: float | None,
        atr: float | None,
        atr_avg: float | None,
    ) -> float:
        macd_diff = macd - macd_signal
        base_signal = 1.0 if macd_diff > 0 else (-1.0 if macd_diff < 0 else 0.0)

        vol_mult = 1.0
        if volume is not None and volume_avg is not None and volume_avg > 0:
            vol_ratio = volume / volume_avg
            vol_mult = min(max(vol_ratio, 0.5), 2.0)

        atr_mult = 1.0
        if atr is not None and atr_avg is not None and atr_avg > 0:
            atr_ratio = atr / atr_avg
            atr_mult = min(max(atr_ratio, 0.5), 2.0)

        vpvma = base_signal * vol_mult * atr_mult * 0.5
        return max(-1.0, min(1.0, vpvma))

    @staticmethod
    def _compute_strength_fusion(
        fusion_magnitude: float,
        confirming_count: int,
        total_indicators: int,
    ) -> float:
        confirmation = confirming_count / max(total_indicators, 1)
        magnitude_score = min(fusion_magnitude * 2, 1.0)
        raw = 0.6 * confirmation + 0.4 * magnitude_score
        return round(max(0.0, min(raw, 1.0)), 4)
