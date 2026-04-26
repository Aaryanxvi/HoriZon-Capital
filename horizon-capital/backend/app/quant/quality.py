"""Quality factor (Asness, Frazzini, Pedersen 2013 — QMJ).

QMJ = Quality Minus Junk. Quality = Profitable + Growing + Safe + Well-managed.
We simplify to 4 fundamentals available from yfinance:

  Profitability  : ROE, gross margin
  Growth         : earnings growth (TTM)
  Safety         : low debt/equity, low beta
  Payout         : dividend yield (light proxy for management discipline)

Each metric ranked cross-sectionally and z-scored. Composite = mean of z-scores.
Higher = more 'quality'. Use as tilt on top of momentum.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import yfinance as yf


@dataclass
class QualityScore:
    symbol: str
    roe: float | None = None
    gross_margin: float | None = None
    earnings_growth: float | None = None
    debt_to_equity: float | None = None
    beta: float | None = None
    composite: float = 0.0
    reasoning: str = ""


def fetch_fundamentals(symbol: str) -> QualityScore:
    """Pull what yfinance gives us. Best-effort — many fields can be None."""
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        info = {}
    score = QualityScore(symbol=symbol)
    score.roe = info.get("returnOnEquity")
    score.gross_margin = info.get("grossMargins")
    score.earnings_growth = info.get("earningsQuarterlyGrowth") or info.get("earningsGrowth")
    score.debt_to_equity = info.get("debtToEquity")
    score.beta = info.get("beta")
    return score


def cross_section_quality(symbols: list[str]) -> dict[str, QualityScore]:
    """Compute cross-sectional z-score composite for given symbols."""
    raw = {s: fetch_fundamentals(s) for s in symbols}

    def collect(attr: str, sign: int = 1) -> dict[str, float]:
        vals = {s: getattr(r, attr) for s, r in raw.items()
                if getattr(r, attr) is not None and not math.isnan(getattr(r, attr))}
        if len(vals) < 2:
            return {}
        mean = sum(vals.values()) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals.values()) / max(len(vals) - 1, 1)) ** 0.5
        if sd == 0:
            return {s: 0.0 for s in vals}
        return {s: sign * (v - mean) / sd for s, v in vals.items()}

    z_roe = collect("roe", +1)
    z_gm = collect("gross_margin", +1)
    z_eg = collect("earnings_growth", +1)
    z_de = collect("debt_to_equity", -1)   # lower is better
    z_beta = collect("beta", -1)           # lower vol -> safer

    for s, score in raw.items():
        parts = [z_roe.get(s, 0.0), z_gm.get(s, 0.0), z_eg.get(s, 0.0),
                 z_de.get(s, 0.0), z_beta.get(s, 0.0)]
        score.composite = sum(parts) / len(parts)
        score.reasoning = (
            f"z(roe)={z_roe.get(s, 0):.2f} z(gm)={z_gm.get(s, 0):.2f} "
            f"z(eg)={z_eg.get(s, 0):.2f} z(de)={z_de.get(s, 0):.2f} "
            f"z(beta)={z_beta.get(s, 0):.2f}"
        )
    return raw
