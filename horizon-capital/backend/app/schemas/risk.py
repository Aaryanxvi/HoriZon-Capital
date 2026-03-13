"""Risk management schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class RiskMetricsResponse(BaseModel):
    """Current portfolio risk metrics."""

    var_95: float = Field(..., description="Value at Risk at the 95th percentile")
    var_99: float = Field(..., description="Value at Risk at the 99th percentile")
    cvar_95: float = Field(..., description="Conditional VaR (Expected Shortfall) at 95%")
    max_drawdown: float
    current_drawdown: float
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    beta: float | None = None
    volatility: float
    correlation_to_benchmark: float | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class RiskLimitResponse(BaseModel):
    """A single risk limit definition and its current utilisation."""

    id: str
    name: str
    limit_type: str = Field(..., description="'drawdown', 'var', 'exposure', 'concentration', 'position_size'")
    limit_value: float
    current_value: float
    utilisation: float = Field(..., ge=0.0, description="current_value / limit_value as a fraction")
    breached: bool
    last_checked: datetime

    model_config = {"from_attributes": True}


class KillSwitchRequest(BaseModel):
    """Request to activate or deactivate the portfolio kill switch."""

    activate: bool
    reason: str = Field(..., min_length=5)
    requested_by: str
