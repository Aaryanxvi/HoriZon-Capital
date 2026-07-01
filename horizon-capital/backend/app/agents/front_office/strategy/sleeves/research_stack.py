"""Research-stack sleeve — combines HRP + Half-Kelly + GMM regime + Quality.

This is the production wiring of the v4 backtest stack.

References (each component traces to a paper):
  * Lopez de Prado 2016 — Hierarchical Risk Parity (replaces inverse-vol)
  * Thorp 1969 / Kelly 1956 — Half-Kelly per-asset sizing
  * Hamilton 1989 (GMM substitute) — 2-state regime gate via Gaussian Mixture
  * Asness, Frazzini, Pedersen 2013 — Quality factor tilt (QMJ)
  * Moskowitz, Ooi, Pedersen 2012 — Time-series momentum 12-1
  * Lopez de Prado 2014 — PSR/DSR for honest evaluation (used in metrics dashboard)

Interface:
  compute(bars, as_of) -> list[SleeveSignal] with target_weight in [0, 1]
  per symbol; the host sleeve has target_weight=0.6 (dominant alpha source).

Design:
  * Risk-off regime  -> 100% defense (TLT/GLD inverse-vol). All other weights 0.
  * Risk-on regime   -> rank universe by TSMOM + Quality, take top-N,
                        weight by HRP, scale per-asset by Half-Kelly cap.
"""
from __future__ import annotations

import math

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal
from app.quant.hrp import hrp_weights
from app.quant.kelly import kelly_size_per_asset
from app.quant.quality import cross_section_quality
from app.quant.regime_hmm import detect_regime

# Universe split: risk vs defense. Symbols use the repo's <ticker>.<exchange>
# notation; the agent strips suffix for yfinance.
_RISK_UNIVERSE = [
    "SPY.NYSE", "QQQ.NASDAQ", "AAPL.NASDAQ", "MSFT.NASDAQ", "NVDA.NASDAQ",
    "GOOGL.NASDAQ", "AMZN.NASDAQ", "META.NASDAQ", "TSLA.NASDAQ",
    "AVGO.NASDAQ", "NFLX.NASDAQ", "COST.NASDAQ", "ORCL.NYSE",
    "V.NYSE", "MA.NYSE", "UNH.NYSE", "LLY.NYSE", "JPM.NYSE",
    "XOM.NYSE", "XLE.NYSE", "XLK.NYSE", "XLF.NYSE",
    "XLV.NYSE", "XLY.NYSE", "XLI.NYSE",
]
_DEFENSE_UNIVERSE = ["TLT.NASDAQ", "GLD.NYSE"]

_TSMOM_LOOKBACK = 252
_TSMOM_SKIP = 21
_HRP_LOOKBACK = 126
_KELLY_LOOKBACK = 252
_TOP_N = 5
_KELLY_FRACTIONAL = 0.5
_KELLY_CAP = 1.0
_QUALITY_WEIGHT = 0.20
_MAX_GROSS = 1.0  # this sleeve internally caps gross at 1; sleeve's outer
                  # target_weight controls overall portfolio share


def _strip_suffix(sym: str) -> str:
    return sym.split(".", 1)[0]


def _tsmom(close: pd.Series) -> float | None:
    if len(close) < _TSMOM_LOOKBACK + 1:
        return None
    past = close.iloc[-_TSMOM_LOOKBACK]
    recent = close.iloc[-_TSMOM_SKIP] if _TSMOM_SKIP > 0 else close.iloc[-1]
    if past <= 0:
        return None
    return float((recent - past) / past)


class ResearchStackSleeve(BaseSleeve):
    """HRP + Half-Kelly + HMM regime + Quality tilt — production wiring."""

    name = "research_stack"
    target_weight = 0.60   # dominant alpha sleeve
    rebalance_days = 5     # weekly

    _quality_cache: dict[str, float] | None = None
    _quality_cache_day: pd.Timestamp | None = None

    def _get_quality(self, symbols: list[str], as_of: pd.Timestamp) -> dict[str, float]:
        # Refresh quality scores at most once per calendar day (live system).
        # In backtest these are fetched once and kept (point-in-time bias noted).
        if self._quality_cache is None or (
            self._quality_cache_day is not None
            and (as_of.normalize() - self._quality_cache_day.normalize()).days >= 1
        ):
            try:
                rs = cross_section_quality([_strip_suffix(s) for s in symbols])
                # remap back to suffixed symbols
                cache: dict[str, float] = {}
                for sym in symbols:
                    raw = _strip_suffix(sym)
                    qs = rs.get(raw)
                    cache[sym] = qs.composite if qs is not None else 0.0
                self._quality_cache = cache
                self._quality_cache_day = as_of
            except Exception:
                self._quality_cache = {s: 0.0 for s in symbols}
                self._quality_cache_day = as_of
        return self._quality_cache

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        # Build SPY history for regime detection.
        spy_key = next((s for s in bars if s.startswith("SPY")), None)
        if spy_key is None:
            return []
        spy_close = bars[spy_key].loc[:as_of]["close"]
        state, conf = detect_regime(spy_close)

        # RISK_OFF -> rotate to defense
        if state == "RISK_OFF":
            defs_present = [s for s in _DEFENSE_UNIVERSE if s in bars]
            if not defs_present:
                return []
            # Inverse-vol within defense
            vols: dict[str, float] = {}
            for s in defs_present:
                rets = bars[s].loc[:as_of]["close"].pct_change().dropna().tail(60)
                v = float(rets.std() * math.sqrt(252)) if len(rets) >= 30 else None
                if v and v > 0:
                    vols[s] = v
            if not vols:
                return [SleeveSignal(s, 1.0/len(defs_present),
                                     reason=f"RISK_OFF (conf={conf:.2f}) -> equal-weight defense")
                        for s in defs_present]
            inv = {s: 1.0/v for s, v in vols.items()}
            total = sum(inv.values())
            return [
                SleeveSignal(
                    symbol=s,
                    target_weight=inv[s] / total,
                    reason=f"RISK_OFF conf={conf:.2f}; inv-vol defense vol={vols[s]:.2%}",
                )
                for s in defs_present
            ]

        # RISK_ON -> score risk universe
        candidates = [s for s in _RISK_UNIVERSE if s in bars]
        if not candidates:
            return []

        qual = self._get_quality(candidates, as_of)
        combined: dict[str, float] = {}
        details: dict[str, str] = {}
        for s in candidates:
            hist = bars[s].loc[:as_of]["close"]
            ts = _tsmom(hist)
            if ts is None:
                continue
            q = qual.get(s, 0.0)
            score = ts + _QUALITY_WEIGHT * q
            combined[s] = score
            details[s] = f"tsmom={ts:+.2%} qual={q:+.2f} score={score:+.3f}"

        positive = {s: v for s, v in combined.items() if v > 0}
        if not positive:
            return []

        ranked = sorted(positive.items(), key=lambda kv: kv[1], reverse=True)
        winners = [s for s, _ in ranked[:_TOP_N]]

        # HRP weights
        rets_panel = pd.DataFrame({
            s: bars[s].loc[:as_of]["close"].pct_change().tail(_HRP_LOOKBACK)
            for s in winners
        }).dropna()
        if rets_panel.shape[0] < 30 or rets_panel.shape[1] < 2:
            hrp = pd.Series([1.0 / len(winners)] * len(winners), index=winners)
        else:
            hrp = hrp_weights(rets_panel)
            if hrp.sum() == 0:
                hrp = pd.Series([1.0 / len(winners)] * len(winners), index=winners)

        # Half-Kelly per asset
        kelly_panel = pd.DataFrame({
            s: bars[s].loc[:as_of]["close"].pct_change().tail(_KELLY_LOOKBACK)
            for s in winners
        }).dropna()
        kelly_caps = kelly_size_per_asset(
            kelly_panel, cap=_KELLY_CAP, fractional=_KELLY_FRACTIONAL
        )

        raw = {s: float(hrp.get(s, 0)) * kelly_caps.get(s, 0) for s in winners}
        total = sum(raw.values())
        if total <= 0:
            return []
        if total > _MAX_GROSS:
            scale = _MAX_GROSS / total
            raw = {s: w * scale for s, w in raw.items()}

        return [
            SleeveSignal(
                symbol=s,
                target_weight=raw[s],
                reason=(
                    f"RISK_ON conf={conf:.2f}; {details.get(s, '')} "
                    f"hrp={hrp.get(s, 0):.2f} kelly={kelly_caps.get(s, 0):.2f} "
                    f"-> w={raw[s]:.2%}"
                ),
            )
            for s in winners
        ]
