"""Chief Investment Officer (CIO) control-plane schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ModeChangeRequest(BaseModel):
    """Request to switch the system operating mode."""

    mode: str = Field(..., pattern="^(aggressive|moderate|conservative|defensive|halt)$")
    reason: str = Field(..., min_length=5)
    requested_by: str
    effective_at: datetime | None = Field(None, description="If None, takes effect immediately")


class OverrideRequest(BaseModel):
    """CIO override of an agent decision or risk limit."""

    override_type: str = Field(..., description="'agent_decision', 'risk_limit', 'position_limit', 'signal'")
    target_id: str = Field(..., description="ID of the entity being overridden")
    action: str = Field(..., description="'approve', 'reject', 'modify'")
    parameters: dict[str, str | float | bool] = Field(default_factory=dict, description="Override-specific parameters")
    reason: str = Field(..., min_length=5)
    requested_by: str
    expires_at: datetime | None = None


class SystemStatus(BaseModel):
    """Full system health and operational status."""

    mode: str = Field(..., description="Current operating mode")
    is_trading: bool
    kill_switch_active: bool
    active_agents: int
    paused_agents: int
    errored_agents: int
    open_positions: int
    pending_orders: int
    nav: float
    daily_pnl: float
    current_drawdown: float
    risk_utilisation: float = Field(..., ge=0.0, description="Aggregate risk limit usage")
    active_debates: int
    last_signal_at: datetime | None = None
    last_trade_at: datetime | None = None
    uptime_seconds: float
    timestamp: datetime

    model_config = {"from_attributes": True}
