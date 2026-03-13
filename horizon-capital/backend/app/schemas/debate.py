"""Multi-agent debate session schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class DebateArgumentResponse(BaseModel):
    """A single argument made by an agent during a debate round."""

    id: str
    debate_id: str
    agent_id: str
    agent_type: str
    position: str = Field(..., description="'for', 'against', 'neutral'")
    argument: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: dict[str, float | str] = Field(default_factory=dict)
    round_number: int = Field(..., ge=1)
    created_at: datetime

    model_config = {"from_attributes": True}


class DebateSessionResponse(BaseModel):
    """Full debate session including all arguments and the final resolution."""

    id: str
    topic: str = Field(..., description="E.g. 'Open long position in AAPL'")
    status: str = Field(..., description="'in_progress', 'concluded', 'cancelled'")
    participants: list[str] = Field(..., description="List of agent IDs involved")
    arguments: list[DebateArgumentResponse]
    rounds_completed: int
    max_rounds: int
    resolution: str | None = Field(None, description="Final decision after debate concludes")
    resolution_confidence: float | None = Field(None, ge=0.0, le=1.0)
    started_at: datetime
    concluded_at: datetime | None = None

    model_config = {"from_attributes": True}
