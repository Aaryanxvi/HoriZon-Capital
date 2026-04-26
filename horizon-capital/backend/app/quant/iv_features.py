"""Option-implied volatility features.

References:
  * Bali, Beckmeyer, Mörke, Weigert 2023 — IV-based predictors of equity returns
  * Cremers, Weinbaum 2010 — call-put IV spread predicts returns
  * Bollerslev, Tauchen, Zhou 2009 — variance risk premium

We pull yfinance option chain (free, US equities) and compute:
  * IV skew    : 25-delta put IV - 25-delta call IV (panic gauge)
  * IV term    : 90d IV - 30d IV (term structure carry)
  * CP spread  : ATM call IV - ATM put IV (signed sentiment from options)

NOTE: yfinance options data is current snapshot only — no historical IV. For
backtests use as a real-time signal at run time, or persist daily snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yfinance as yf


@dataclass
class IVFeatures:
    symbol: str
    spot: float | None = None
    iv_30d_atm_call: float | None = None
    iv_30d_atm_put: float | None = None
    iv_skew_30d: float | None = None    # 25d-put IV - 25d-call IV
    iv_term_90_30: float | None = None  # 90d ATM IV - 30d ATM IV
    cp_iv_spread: float | None = None   # ATM call IV - ATM put IV
    reasoning: str = ""


def _atm_iv(chain: pd.DataFrame, spot: float, side: str) -> float | None:
    if chain is None or chain.empty or spot is None:
        return None
    chain = chain.dropna(subset=["impliedVolatility"])
    if chain.empty:
        return None
    chain = chain.copy()
    chain["dist"] = (chain["strike"] - spot).abs()
    return float(chain.sort_values("dist").iloc[0]["impliedVolatility"])


def _delta_iv(chain: pd.DataFrame, spot: float, target_delta: float) -> float | None:
    """Approximate IV at target delta using moneyness as proxy."""
    if chain is None or chain.empty or spot is None:
        return None
    chain = chain.dropna(subset=["impliedVolatility"]).copy()
    if chain.empty:
        return None
    # rough: 25d put ~ strike at 0.92*spot, 25d call ~ 1.08*spot
    chain["m"] = chain["strike"] / spot
    target = 0.92 if target_delta < 0 else 1.08
    chain["d"] = (chain["m"] - target).abs()
    return float(chain.sort_values("d").iloc[0]["impliedVolatility"])


def compute_iv_features(symbol: str) -> IVFeatures:
    out = IVFeatures(symbol=symbol)
    try:
        tk = yf.Ticker(symbol)
        spot = float(tk.history(period="1d")["Close"].iloc[-1])
        out.spot = spot
        expiries = tk.options
        if not expiries or len(expiries) < 2:
            return out

        today = datetime.utcnow()
        # Find nearest-30d and nearest-90d expiries
        with_dte = []
        for e in expiries:
            try:
                dte = (datetime.fromisoformat(e) - today).days
                if dte > 0:
                    with_dte.append((dte, e))
            except Exception:
                continue
        if not with_dte:
            return out
        exp_30 = min(with_dte, key=lambda x: abs(x[0] - 30))[1]
        exp_90 = min(with_dte, key=lambda x: abs(x[0] - 90))[1]

        ch30 = tk.option_chain(exp_30)
        ch90 = tk.option_chain(exp_90)

        atm_call_30 = _atm_iv(ch30.calls, spot, "call")
        atm_put_30 = _atm_iv(ch30.puts, spot, "put")
        atm_call_90 = _atm_iv(ch90.calls, spot, "call")

        put_25d = _delta_iv(ch30.puts, spot, -0.25)
        call_25d = _delta_iv(ch30.calls, spot, +0.25)

        out.iv_30d_atm_call = atm_call_30
        out.iv_30d_atm_put = atm_put_30
        if put_25d and call_25d:
            out.iv_skew_30d = put_25d - call_25d
        if atm_call_90 and atm_call_30:
            out.iv_term_90_30 = atm_call_90 - atm_call_30
        if atm_call_30 and atm_put_30:
            out.cp_iv_spread = atm_call_30 - atm_put_30
        out.reasoning = (
            f"spot={spot:.2f} atm30c={atm_call_30} atm30p={atm_put_30} "
            f"skew={out.iv_skew_30d} term={out.iv_term_90_30} cp_sp={out.cp_iv_spread}"
        )
    except Exception as e:
        out.reasoning = f"error: {e}"
    return out


def iv_signal_score(feat: IVFeatures) -> float:
    """Combine IV features into a single forecast in [-1, +1].

    Heuristic mapping based on Cremers-Weinbaum (positive CP spread bullish),
    skew (high skew bearish), term (steep contango bullish).
    """
    if feat.cp_iv_spread is None and feat.iv_skew_30d is None:
        return 0.0
    parts: list[float] = []
    if feat.cp_iv_spread is not None:
        # call IV > put IV bullish — but rare. typical -2% to +1%
        parts.append(max(-1.0, min(1.0, feat.cp_iv_spread * 50)))
    if feat.iv_skew_30d is not None:
        # high put skew bearish — typical +2% to +10%
        parts.append(max(-1.0, min(1.0, -feat.iv_skew_30d * 20)))
    if feat.iv_term_90_30 is not None:
        # contango (90d > 30d) = calm = bullish
        parts.append(max(-1.0, min(1.0, feat.iv_term_90_30 * 25)))
    return sum(parts) / max(len(parts), 1)
