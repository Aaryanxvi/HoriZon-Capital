# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-765F0ED88DBA
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Performance and attribution schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class PerformanceSummary(BaseModel):
    """Aggregated performance metrics over a given period."""

    period: str = Field(..., description="'1d', '1w', '1m', '3m', 'ytd', '1y', 'inception'")
    total_return: float
    annualised_return: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float
    win_rate: float = Field(..., ge=0.0, le=1.0)
    profit_factor: float | None = None
    total_trades: int
    avg_trade_pnl: float
    best_trade_pnl: float
    worst_trade_pnl: float
    volatility: float
    timestamp: datetime

    model_config = {"from_attributes": True}


class AttributionResponse(BaseModel):
    """PnL attribution broken down by strategy, sector, or factor."""

    period: str
    total_pnl: float
    by_strategy: dict[str, float] = Field(
        default_factory=dict, description="PnL keyed by strategy name"
    )
    by_symbol: dict[str, float] = Field(
        default_factory=dict, description="PnL keyed by ticker symbol"
    )
    by_sector: dict[str, float] = Field(default_factory=dict, description="PnL keyed by sector")
    by_factor: dict[str, float] = Field(
        default_factory=dict, description="PnL keyed by risk factor"
    )
    timestamp: datetime

    model_config = {"from_attributes": True}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 765F0ED88DBA - verify with scripts/authorship.py verify
