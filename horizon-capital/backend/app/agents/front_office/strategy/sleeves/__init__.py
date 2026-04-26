"""Multi-sleeve strategy portfolio.

Each sleeve is an independent return source with a documented thesis. The
portfolio holds them in fixed target weights; their combined low correlation
is what historically delivers positive risk-adjusted returns at retail scale.

Sleeves:
- ``research_stack``: HRP + Half-Kelly + GMM regime + Quality tilt (60% target).
- ``trend_filter``:   Faber 200d SMA regime gate on SPY (20%).
- ``gap_fade``:       Buy QQQ on open after gap-down, exit at close (10%).
- ``momentum_rank``:  Monthly 12-1 momentum top-3 (10%).
"""

from app.agents.front_office.strategy.sleeves.gap_fade import GapFadeSleeve
from app.agents.front_office.strategy.sleeves.momentum_rank import MomentumRankSleeve
from app.agents.front_office.strategy.sleeves.research_stack import ResearchStackSleeve
from app.agents.front_office.strategy.sleeves.trend_filter import TrendFilterSleeve

__all__ = [
    "GapFadeSleeve",
    "MomentumRankSleeve",
    "ResearchStackSleeve",
    "TrendFilterSleeve",
]
