"""Agent lifecycle and state schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class AgentStateResponse(BaseModel):
    """Current operational state of an AI agent."""

    agent_id: str
    agent_type: str = Field(
        ..., description="'regime', 'strategy', 'risk', 'portfolio', 'sentiment', 'execution'"
    )
    status: str = Field(..., description="'running', 'paused', 'error', 'stopped'")
    uptime_seconds: float
    last_heartbeat: datetime
    current_task: str | None = None
    error_message: str | None = None
    config: dict[str, str | float | bool] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(
        default_factory=dict, description="Agent-specific runtime metrics"
    )

    model_config = {"from_attributes": True}


class AgentPauseRequest(BaseModel):
    """Request to pause or resume an agent."""

    agent_id: str
    pause: bool = Field(..., description="True to pause, False to resume")
    reason: str | None = None
    requested_by: str
