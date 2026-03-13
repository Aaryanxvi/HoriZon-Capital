"""Narrative and sentiment endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.narratives import Narrative, SentimentAggregate

router = APIRouter(prefix="/narratives", tags=["narratives"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NarrativeOut(BaseModel):
    id: UUID
    symbol: str
    source: str
    headline: str
    url: str | None = None
    sentiment_score: float
    relevance_score: float
    engagement_score: float
    lifecycle_stage: str | None = None
    published_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NarrativeListResponse(BaseModel):
    narratives: list[NarrativeOut]
    count: int


class SentimentAggregateOut(BaseModel):
    id: UUID
    symbol: str
    window: str
    avg_sentiment: float
    article_count: int
    bull_pct: float
    bear_pct: float
    neutral_pct: float
    created_at: datetime

    model_config = {"from_attributes": True}


class SentimentResponse(BaseModel):
    symbol: str
    aggregates: list[SentimentAggregateOut]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=NarrativeListResponse)
async def list_narratives(
    symbol: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> NarrativeListResponse:
    """List narratives with optional filters."""
    stmt = select(Narrative).order_by(Narrative.published_at.desc().nulls_last())

    if symbol:
        stmt = stmt.where(Narrative.symbol == symbol)
    if source:
        stmt = stmt.where(Narrative.source == source)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return NarrativeListResponse(
        narratives=[NarrativeOut.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.get("/sentiment/{symbol}", response_model=SentimentResponse)
async def get_sentiment(
    symbol: str,
    window: str | None = Query(None, description="Filter by window: 1h, 4h, 24h, 14d"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> SentimentResponse:
    """Get aggregated sentiment data for a symbol across time windows."""
    stmt = (
        select(SentimentAggregate)
        .where(SentimentAggregate.symbol == symbol)
        .order_by(SentimentAggregate.created_at.desc())
    )

    if window:
        stmt = stmt.where(SentimentAggregate.window == window)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return SentimentResponse(
        symbol=symbol,
        aggregates=[SentimentAggregateOut.model_validate(r) for r in rows],
    )
