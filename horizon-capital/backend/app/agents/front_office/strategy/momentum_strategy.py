"""Momentum strategy -- active in BULL regimes.

Uses VPVMA (Volume-Price-Volatility Modified MACD) + multi-indicator fusion
scoring with RSI, MACD, EMA, VWAP, and volume confirmation.

References
----------
- "Volume-Price-Volatility Modified MACD" (arXiv 2206.12282, 2022)
  — MACD incorporating volume + volatility; improved win-rate.
- "Combined MACD+RSI+MFI Performance" (J. Autonomous Intelligence, 2024)
  — Multi-indicator fusion achieves 0.84-0.86 win-rate.
- "Multi-Factor Indicator Fusion (RSI + EMA + VWAP + MACD)"
  (Procedia Computer Science, Elsevier, 2025) — 60.63% profitable trades.
"""

from __future__ import annotations

from typing import Any

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):

    @property
    def llm_system_prompt(self) -> str:
        return (
            "You are an aggressive momentum trader. You use VPVMA (volume-price-"
            "volatility modified MACD), multi-indicator fusion, and volume confirmation "
            "to identify strong trends. You believe trends persist and the best time "
            "to buy is when momentum is building across multiple confirming indicators. "
            "Analyze the given indicators and return a JSON signal. "
            '{"direction": 1|-1|0, "strength": 0.0-1.0, "reasoning": "..."}'
        )

    @property
    def name(self) -> str:
        return "momentum"

    @property
    def active_regimes(self) -> list[str]:
        return ["BULL"]

    def generate_signal(
        self,
        symbol: str,
        features: dict[str, Any],
        regime: str,
    ) -> Signal | None:
        rsi = features.get("rsi")
        macd = features.get("macd")
        macd_signal = features.get("macd_signal")
        ema_20 = features.get("ema_20")
        close = features.get("close")

        if any(v is None for v in [rsi, macd, macd_signal, ema_20, close]):
            return None

        # Optional enhanced indicators
        volume = features.get("volume")
        volume_avg = features.get("volume_avg_20")
        vwap = features.get("vwap")
        atr = features.get("atr")
        atr_avg_20 = features.get("atr_avg_20")

        # ----- Compute VPVMA (Volume-Price-Volatility Modified MACD) -----
        vpvma_score = self._compute_vpvma(
            macd, macd_signal, volume, volume_avg, atr, atr_avg_20
        )

        # ----- Multi-indicator fusion scoring -----
        # Each indicator contributes a sub-score in [0, 1]
        indicators: dict[str, float] = {}

        # 1. RSI component
        if rsi < 30:
            indicators["rsi"] = (30 - rsi) / 30  # stronger when more oversold
        elif rsi > 70:
            indicators["rsi"] = -(rsi - 70) / 30  # negative when overbought
        else:
            # Trend strength: RSI above 50 is bullish momentum
            indicators["rsi"] = (rsi - 50) / 50 * 0.3

        # 2. MACD crossover component
        macd_spread = macd - macd_signal
        macd_magnitude = abs(macd_spread) / (abs(macd_signal) + 1e-8)
        indicators["macd"] = min(macd_magnitude, 1.0) * (1 if macd_spread > 0 else -1)

        # 3. VPVMA component
        indicators["vpvma"] = vpvma_score

        # 4. Price vs EMA component
        ema_deviation = (close - ema_20) / ema_20 if ema_20 > 0 else 0.0
        indicators["ema_trend"] = max(-1.0, min(1.0, ema_deviation * 10))

        # 5. Volume confirmation (if available)
        if volume is not None and volume_avg is not None and volume_avg > 0:
            vol_ratio = volume / volume_avg
            indicators["volume"] = min(vol_ratio - 1.0, 1.0)  # positive = above avg
        else:
            indicators["volume"] = 0.0

        # 6. VWAP confirmation (if available)
        if vwap is not None and vwap > 0:
            vwap_dev = (close - vwap) / vwap
            indicators["vwap"] = max(-1.0, min(1.0, vwap_dev * 20))
        else:
            indicators["vwap"] = 0.0

        # ----- Fusion: weighted combination -----
        # Weights based on research: MACD+RSI most important (0.84-0.86 win-rate combined)
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

        # Count confirming indicators (positive = bullish, negative = bearish)
        bullish_count = sum(1 for v in indicators.values() if v > 0.1)
        bearish_count = sum(1 for v in indicators.values() if v < -0.1)

        meta = {
            "rsi": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "ema_20": ema_20,
            "close": close,
            "fusion_score": round(fusion_score, 4),
            "vpvma_score": round(vpvma_score, 4),
            "bullish_indicators": bullish_count,
            "bearish_indicators": bearish_count,
            "indicator_scores": {k: round(v, 4) for k, v in indicators.items()},
        }

        # ----- BUY: strong bullish fusion + sufficient confirmation -----
        if fusion_score > 0.15 and bullish_count >= 3:
            strength = self._compute_strength_fusion(
                fusion_score, bullish_count, len(indicators)
            )
            return Signal(
                symbol=symbol,
                direction=1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Momentum BUY: fusion={fusion_score:.3f}, "
                    f"{bullish_count}/{len(indicators)} indicators bullish, "
                    f"RSI={rsi:.1f}, MACD spread={macd - macd_signal:.4f}"
                ),
                meta=meta,
            )

        # ----- SELL: strong bearish fusion -----
        if fusion_score < -0.15 and bearish_count >= 3:
            strength = self._compute_strength_fusion(
                abs(fusion_score), bearish_count, len(indicators)
            )
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=strength,
                strategy_name=self.name,
                regime=regime,
                reasoning=(
                    f"Momentum SELL: fusion={fusion_score:.3f}, "
                    f"{bearish_count}/{len(indicators)} indicators bearish, "
                    f"RSI={rsi:.1f}"
                ),
                meta=meta,
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
        """Compute VPVMA: Volume-Price-Volatility Modified MACD score.

        Amplifies MACD signal when volume is above average and volatility
        is expanding (favorable for momentum), dampens when volume is low
        or volatility is contracting.
        """
        # Base MACD signal
        macd_diff = macd - macd_signal
        base_signal = 1.0 if macd_diff > 0 else (-1.0 if macd_diff < 0 else 0.0)

        # Volume multiplier
        vol_mult = 1.0
        if volume is not None and volume_avg is not None and volume_avg > 0:
            vol_ratio = volume / volume_avg
            vol_mult = min(max(vol_ratio, 0.5), 2.0)  # clamp [0.5, 2.0]

        # Volatility multiplier (expanding vol = stronger momentum)
        atr_mult = 1.0
        if atr is not None and atr_avg is not None and atr_avg > 0:
            atr_ratio = atr / atr_avg
            atr_mult = min(max(atr_ratio, 0.5), 2.0)

        # VPVMA score: base * volume_weight * volatility_weight
        vpvma = base_signal * vol_mult * atr_mult * 0.5
        return max(-1.0, min(1.0, vpvma))

    @staticmethod
    def _compute_strength_fusion(
        fusion_magnitude: float,
        confirming_count: int,
        total_indicators: int,
    ) -> float:
        """Compute signal strength from fusion score and confirmation count."""
        # Confirmation ratio (how many indicators agree)
        confirmation = confirming_count / max(total_indicators, 1)

        # Fusion magnitude contribution
        magnitude_score = min(fusion_magnitude * 2, 1.0)

        # Weighted: 60% confirmation, 40% magnitude
        raw = 0.6 * confirmation + 0.4 * magnitude_score
        return round(max(0.0, min(raw, 1.0)), 4)
