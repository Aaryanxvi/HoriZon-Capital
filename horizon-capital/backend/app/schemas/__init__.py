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
