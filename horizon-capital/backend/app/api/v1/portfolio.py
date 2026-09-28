# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-6C963A759E0A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Portfolio endpoints: summary snapshot and current positions."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.portfolio import PortfolioSnapshot
from app.models.trades import Position

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PortfolioSummaryOut(BaseModel):
    id: UUID
    total_value: float
    cash_inr: float
    cash_usd: float
    equity_value: float
    crypto_value: float
    fno_value: float
    gross_leverage: float
    net_leverage: float
    usd_inr_rate: float
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    side: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    weight_pct: float
    currency: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class PositionListResponse(BaseModel):
    positions: list[PositionOut]
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=PortfolioSummaryOut)
async def get_portfolio_summary(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PortfolioSummaryOut:
    """Return the most recent portfolio snapshot."""
    stmt = (
        select(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolio snapshot available",
        )

    return PortfolioSummaryOut.model_validate(snapshot)


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PositionListResponse:
    """List all current positions (non-zero quantity)."""
    stmt = (
        select(Position)
        .where(Position.quantity != 0)
        .order_by(Position.symbol)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return PositionListResponse(
        positions=[PositionOut.model_validate(r) for r in rows],
        count=len(rows),
    )
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 6C963A759E0A - verify with scripts/authorship.py verify
