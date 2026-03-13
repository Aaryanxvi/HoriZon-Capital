"""Signal endpoints: list all signals, list active signals."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.signals import Signal

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalOut(BaseModel):
    id: UUID
    agent_id: str
    symbol: str
    exchange: str
    direction: int
    strength: float
    target_price: float | None = None
    stop_loss: float | None = None
    reasoning: str | None = None
    strategy_name: str
    regime_at_signal: str | None = None
    expires_at: datetime | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalListResponse(BaseModel):
    signals: list[SignalOut]
    count: int


@router.get("", response_model=SignalListResponse)
async def list_signals(
    symbol: str | None = Query(None),
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> SignalListResponse:
    """List all signals with optional filters."""
    stmt = select(Signal).order_by(Signal.created_at.desc())

    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if agent_id:
        stmt = stmt.where(Signal.agent_id == agent_id)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return SignalListResponse(
        signals=[SignalOut.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.get("/active", response_model=SignalListResponse)
async def list_active_signals(
    symbol: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> SignalListResponse:
    """List only active (non-expired) signals."""
    stmt = (
        select(Signal)
        .where(Signal.is_active.is_(True))
        .order_by(Signal.created_at.desc())
    )

    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return SignalListResponse(
        signals=[SignalOut.model_validate(r) for r in rows],
        count=len(rows),
    )
