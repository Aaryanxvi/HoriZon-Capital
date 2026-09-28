# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B1C66E391FBA
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Horizon Capital Pydantic v2 schemas."""

from .agents import AgentPauseRequest, AgentStateResponse
from .auth import LoginRequest, RefreshRequest, TokenResponse
from .cio import ModeChangeRequest, OverrideRequest, SystemStatus
from .debate import DebateArgumentResponse, DebateSessionResponse
from .market_data import (
    NormalizedOHLCV,
    NormalizedTick,
    OHLCVResponse,
    QuoteResponse,
    RegimeResponse,
)
from .narratives import NarrativeResponse, SentimentResponse
from .performance import AttributionResponse, PerformanceSummary
from .portfolio import PortfolioSummary, PositionSummary
from .risk import KillSwitchRequest, RiskLimitResponse, RiskMetricsResponse
from .signals import SignalListResponse, SignalResponse
from .trades import (
    FillResponse,
    OrderCreate,
    OrderResponse,
    PositionResponse,
    TradeApproval,
)

__all__ = [
    # auth
    "LoginRequest",
    "TokenResponse",
    "RefreshRequest",
    # market_data
    "QuoteResponse",
    "OHLCVResponse",
    "RegimeResponse",
    "NormalizedTick",
    "NormalizedOHLCV",
    # signals
    "SignalResponse",
    "SignalListResponse",
    # trades
    "OrderCreate",
    "OrderResponse",
    "FillResponse",
    "PositionResponse",
    "TradeApproval",
    # portfolio
    "PortfolioSummary",
    "PositionSummary",
    # risk
    "RiskMetricsResponse",
    "RiskLimitResponse",
    "KillSwitchRequest",
    # agents
    "AgentStateResponse",
    "AgentPauseRequest",
    # debate
    "DebateSessionResponse",
    "DebateArgumentResponse",
    # narratives
    "NarrativeResponse",
    "SentimentResponse",
    # performance
    "PerformanceSummary",
    "AttributionResponse",
    # cio
    "ModeChangeRequest",
    "OverrideRequest",
    "SystemStatus",
]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B1C66E391FBA - verify with scripts/authorship.py verify

__author__ = "Aaryan Baadkar"
__email__ = "aaryanbaadkar71@gmail.com"
__copyright__ = "Copyright (c) 2026 Aaryan Baadkar"
