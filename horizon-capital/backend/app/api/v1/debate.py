"""Debate endpoints: list sessions, view arguments for a session."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.debate import DebateArgument, DebateSession

router = APIRouter(prefix="/debate", tags=["debate"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DebateSessionOut(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    proposed_action: str
    proposed_quantity: float | None = None
    signal_id: UUID | None = None
    status: str
    final_decision: str | None = None
    consensus_score: float | None = None
    total_rounds: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DebateSessionListResponse(BaseModel):
    sessions: list[DebateSessionOut]
    count: int


class DebateArgumentOut(BaseModel):
    id: UUID
    session_id: UUID
    agent_id: str
    role: str
    argument: str
    vote: str
    confidence: float
    round_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DebateArgumentListResponse(BaseModel):
    session_id: UUID
    arguments: list[DebateArgumentOut]
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=DebateSessionListResponse)
async def list_debate_sessions(
    symbol: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> DebateSessionListResponse:
    """List debate sessions with optional filters."""
    stmt = select(DebateSession).order_by(DebateSession.created_at.desc())

    if symbol:
        stmt = stmt.where(DebateSession.symbol == symbol)
    if status_filter:
        stmt = stmt.where(DebateSession.status == status_filter)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return DebateSessionListResponse(
        sessions=[DebateSessionOut.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.get("/sessions/{session_id}/arguments", response_model=DebateArgumentListResponse)
async def get_debate_arguments(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> DebateArgumentListResponse:
    """Get all arguments for a specific debate session, ordered by round and creation time."""
    # Verify session exists
    session_stmt = select(DebateSession).where(DebateSession.id == session_id)
    session_result = await db.execute(session_stmt)
    session = session_result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Debate session {session_id} not found",
        )

    stmt = (
        select(DebateArgument)
        .where(DebateArgument.session_id == session_id)
        .order_by(DebateArgument.round_number, DebateArgument.created_at)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return DebateArgumentListResponse(
        session_id=session_id,
        arguments=[DebateArgumentOut.model_validate(r) for r in rows],
        count=len(rows),
    )
