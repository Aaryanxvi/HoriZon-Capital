"""Multi-sleeve strategy portfolio.

Each sleeve is an independent return source with a documented thesis. The
portfolio holds them in fixed target weights; their combined low correlation
is what historically delivers positive risk-adjusted returns at retail scale.

Sleeves:
- ``breadth_alpha``:  Multi-signal cross-sectional top-K over the universe (live
                      wiring of the validated breadth engine).
- ``research_stack``: HRP + Half-Kelly + GMM regime + Quality tilt.
- ``dual_momentum``:  Antonacci GEM across asset-class ETFs (monthly).
- ``trend_filter``:   Faber 200d SMA gate on SPY. NOT used live — superseded by
                      the portfolio-level overlay + dual momentum. Kept for
                      reference scripts.
- ``momentum_rank``:  Monthly 12-1 momentum top-3.
- ``gap_fade``:       Buy QQQ on open after gap-down (intraday thesis; NOT used
                      live — degenerate on daily bars. Kept for reference only).
- ``crypto_trend``:   Faber 200d SMA gate on BTC/ETH, or on the top-N coins by
                      market cap when CRYPTO_DISCOVERY_ENABLED. UNVALIDATED,
                      default-off — enable via CRYPTO_SLEEVE_ENABLED.
- ``polymarket_momentum``: 7d probability momentum on Polymarket YES prices,
                      tail-filtered. Markets are hand-listed and/or discovered
                      hourly when POLYMARKET_DISCOVERY_ENABLED. UNVALIDATED,
                      default-off — enable via POLYMARKET_SLEEVE_ENABLED.
"""

from app.agents.front_office.strategy.sleeves.breadth_alpha import BreadthAlphaSleeve
from app.agents.front_office.strategy.sleeves.crypto_trend import CryptoTrendSleeve
from app.agents.front_office.strategy.sleeves.dual_momentum import DualMomentumSleeve
from app.agents.front_office.strategy.sleeves.gap_fade import GapFadeSleeve
from app.agents.front_office.strategy.sleeves.momentum_rank import MomentumRankSleeve
from app.agents.front_office.strategy.sleeves.polymarket_momentum import (
    PolymarketMomentumSleeve,
)
from app.agents.front_office.strategy.sleeves.research_stack import ResearchStackSleeve
from app.agents.front_office.strategy.sleeves.trend_filter import TrendFilterSleeve

__all__ = [
    "BreadthAlphaSleeve",
    "CryptoTrendSleeve",
    "DualMomentumSleeve",
    "GapFadeSleeve",
    "MomentumRankSleeve",
    "PolymarketMomentumSleeve",
    "ResearchStackSleeve",
    "TrendFilterSleeve",
]
