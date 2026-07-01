"""Breadth-alpha sleeve — live wiring of the multi_signal cross-sectional scorer.

Ranks the full configured equity universe each rebalance via the cheap
deterministic scorer (app.quant.multi_signal), takes the top-K by composite
score, and equal-weights them. This is the production wiring of the engine
validated in scripts/validate_breadth.py + strategy_scorecard.py.

The sleeve's internal weights sum to ~1.0 (gross); the sleeve's outer
target_weight (set by StrategyAgent) controls its share of total NAV.

The LLM gate (select_for_llm) caps the output at K names regardless of universe
size, so escalating these to a debate/vet step stays O(K), not O(universe).
"""
from __future__ import annotations

import pandas as pd

from app.agents.front_office.strategy.sleeves.base import BaseSleeve, SleeveSignal
from app.quant.multi_signal import score_universe, select_for_llm

_TOP_K = 25             # the validated config (validate_pit.py: K=25, conv=0.5)
_MIN_CONVICTION = 0.5   # skip weak longs; also keeps a future LLM gate cheap
_MARKET = "SPY"         # used as beta reference, not ranked as a candidate


def _is_crypto(symbol: str) -> bool:
    return symbol.endswith(("-USD", "-USDT")) or ".CRYPTO" in symbol


class BreadthAlphaSleeve(BaseSleeve):
    """Top-K cross-sectional breadth book over the equity universe."""

    name = "breadth_alpha"
    target_weight = 0.40   # overridden per-instance by StrategyAgent
    rebalance_days = 5     # weekly

    def compute(
        self, bars: dict[str, pd.DataFrame], as_of: pd.Timestamp
    ) -> list[SleeveSignal]:
        closes: dict[str, pd.Series] = {}
        market: pd.Series | None = None
        for sym, df in bars.items():
            if df is None or df.empty or "close" not in df:
                continue
            series = df["close"]
            if sym.split(".")[0] == _MARKET:
                market = series          # beta reference
                continue                 # don't rank the index itself
            if _is_crypto(sym):
                continue                 # equity cross-section only
            closes[sym] = series
        if len(closes) < 5:
            return []

        wide = pd.DataFrame(closes).sort_index()
        cands = score_universe(wide, as_of, market=market)
        picks = select_for_llm(cands, k=_TOP_K, min_conviction=_MIN_CONVICTION)
        if not picks:
            return []

        w = 1.0 / len(picks)
        return [
            SleeveSignal(
                symbol=c.symbol,
                target_weight=w,
                reason=f"breadth top{_TOP_K}: composite_z={c.score:+.2f}",
            )
            for c in picks
        ]


def _demo() -> None:
    """Self-check: compute returns equal-weighted top-K SleeveSignals."""
    import numpy as np

    idx = pd.date_range("2022-01-01", periods=300, freq="B")
    rng = np.random.default_rng(0)
    bars: dict[str, pd.DataFrame] = {}
    # SPY as market + several names with varied drift so ranking has structure.
    drifts = {"SPY.NYSE": 0.0003, "AAPL.NASDAQ": 0.0009, "MSFT.NASDAQ": 0.0007,
              "JPM.NYSE": 0.0001, "XOM.NYSE": -0.0002, "KO.NYSE": 0.0002,
              "NVDA.NASDAQ": 0.0012, "WMT.NYSE": 0.0004}
    for sym, mu in drifts.items():
        px = 100 * np.exp(np.cumsum(mu + 0.01 * rng.standard_normal(len(idx))))
        bars[sym] = pd.DataFrame({"open": px, "high": px, "low": px,
                                  "close": px, "volume": 1e6}, index=idx)
    sigs = BreadthAlphaSleeve().compute(bars, idx[-1])
    assert sigs, "expected non-empty signals"
    total = sum(s.target_weight for s in sigs)
    assert abs(total - 1.0) < 1e-6, f"weights should sum to 1.0, got {total}"
    assert "SPY.NYSE" not in {s.symbol for s in sigs}, "market proxy must not be ranked"
    print("breadth_alpha demo OK:", [(s.symbol, round(s.target_weight, 3)) for s in sigs])


if __name__ == "__main__":
    _demo()
