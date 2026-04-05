"""Agent endpoints: list agent states, pause, resume."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.messaging import AgentMessage, MessageType
from app.core.runtime import get_bus, get_db
from app.dependencies import get_current_user
from app.models.agents import AgentState

router = APIRouter(prefix="/agents", tags=["agents"])

# ---------------------------------------------------------------------------
# Status → pixel state mapping
# ---------------------------------------------------------------------------

_STATUS_TO_PIXEL: dict[str, str] = {
    "RUNNING": "ANALYZING",
    "INIT": "IDLE",
    "PAUSED": "IDLE",
    "CRASHED": "ERROR",
    "ERROR": "ERROR",
    "STOPPED": "IDLE",
}

_AGENT_TYPE_DEPARTMENT: dict[str, str] = {
    "strategy-agent": "front_office",
    "strategy_agent": "front_office",
    "sentiment-agent": "front_office",
    "sentiment_agent": "front_office",
    "risk-manager": "middle_office",
    "risk_manager": "middle_office",
    "portfolio-manager": "middle_office",
    "portfolio_manager": "middle_office",
    "debate-moderator": "middle_office",
    "debate_moderator": "middle_office",
    "execution-agent": "back_office",
    "execution_agent": "back_office",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AgentStateOut(BaseModel):
    agent_id: str
    agent_type: str
    status: str
    last_heartbeat: datetime | None = None
    config: dict
    metrics: dict
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    department: str = ""
    pixel_state: str = "IDLE"

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    agents: list[AgentStateOut]
    count: int


class AgentActionResponse(BaseModel):
    agent_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=AgentListResponse)
async def list_agents(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> AgentListResponse:
    """List all registered agent states."""
    stmt = select(AgentState).order_by(AgentState.agent_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    agents = []
    for r in rows:
        out = AgentStateOut.model_validate(r)
        out.department = _AGENT_TYPE_DEPARTMENT.get(out.agent_type, "")
        out.pixel_state = _STATUS_TO_PIXEL.get(out.status, "IDLE")
        agents.append(out)

    return AgentListResponse(agents=agents, count=len(agents))


@router.post("/{agent_id}/pause", response_model=AgentActionResponse)
async def pause_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> AgentActionResponse:
    """Pause a running agent."""
    stmt = select(AgentState).where(AgentState.agent_id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    if agent.status != "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent {agent_id} is {agent.status}, cannot pause",
        )

    agent.status = "PAUSED"
    await db.flush()

    # Notify agent via message bus
    bus = get_bus()
    msg = AgentMessage(
        sender_id="api",
        channel=f"horizon.agent.command.{agent_id}",
        message_type=MessageType.AGENT_STATUS,
        payload={"command": "pause", "agent_id": agent_id},
    )
    await bus.publish(msg)

    return AgentActionResponse(
        agent_id=agent_id,
        status="PAUSED",
        message=f"Agent {agent_id} paused successfully",
    )


@router.post("/{agent_id}/resume", response_model=AgentActionResponse)
async def resume_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> AgentActionResponse:
    """Resume a paused agent."""
    stmt = select(AgentState).where(AgentState.agent_id == agent_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    if agent.status != "PAUSED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent {agent_id} is {agent.status}, cannot resume",
        )

    agent.status = "RUNNING"
    await db.flush()

    bus = get_bus()
    msg = AgentMessage(
        sender_id="api",
        channel=f"horizon.agent.command.{agent_id}",
        message_type=MessageType.AGENT_STATUS,
        payload={"command": "resume", "agent_id": agent_id},
    )
    await bus.publish(msg)

    return AgentActionResponse(
        agent_id=agent_id,
        status="RUNNING",
        message=f"Agent {agent_id} resumed successfully",
    )
