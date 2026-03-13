"""Performance endpoints: summary and attribution."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.performance import PerformanceSnapshot

router = APIRouter(prefix="/performance", tags=["performance"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PerformanceSummaryOut(BaseModel):
    id: UUID
    period: str
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    alpha_india: float
    alpha_us: float
    total_trades: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PerformanceSummaryListResponse(BaseModel):
    snapshots: list[PerformanceSummaryOut]
    count: int


class AttributionEntry(BaseModel):
    strategy: str
    return_contribution: float
    trade_count: int
    win_rate: float


class AttributionResponse(BaseModel):
    period: str
    total_return: float
    attribution: list[AttributionEntry]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=PerformanceSummaryListResponse)
async def get_performance_summary(
    period: str | None = Query(None, description="Filter by period: 1d, 7d, 30d, 90d, YTD, ALL"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> PerformanceSummaryListResponse:
    """Get performance summary snapshots. Returns the latest snapshot per period."""
    if period:
        # Return the most recent snapshot for the given period
        stmt = (
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.period == period)
            .order_by(PerformanceSnapshot.created_at.desc())
            .limit(1)
        )
    else:
        # Return the latest snapshot for each known period using a subquery approach:
        # For simplicity, grab the most recent snapshots across all periods
        stmt = (
            select(PerformanceSnapshot)
            .order_by(PerformanceSnapshot.created_at.desc())
            .limit(20)
        )

    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Deduplicate by period (keep latest)
    seen_periods: set[str] = set()
    deduped: list[PerformanceSnapshot] = []
    for row in rows:
        if row.period not in seen_periods:
            seen_periods.add(row.period)
            deduped.append(row)

    return PerformanceSummaryListResponse(
        snapshots=[PerformanceSummaryOut.model_validate(r) for r in deduped],
        count=len(deduped),
    )


@router.get("/attribution", response_model=AttributionResponse)
async def get_attribution(
    period: str = Query("30d", description="Period: 1d, 7d, 30d, 90d, YTD, ALL"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> AttributionResponse:
    """Get return attribution breakdown by strategy for a given period."""
    stmt = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.period == period)
        .order_by(PerformanceSnapshot.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No performance data for period {period}",
        )

    # The attribution column stores a JSONB dict like:
    # {"momentum": {"return_contribution": 0.05, "trade_count": 12, "win_rate": 0.67}, ...}
    attribution_data = snapshot.attribution or {}
    entries = [
        AttributionEntry(
            strategy=strategy,
            return_contribution=details.get("return_contribution", 0.0),
            trade_count=details.get("trade_count", 0),
            win_rate=details.get("win_rate", 0.0),
        )
        for strategy, details in attribution_data.items()
        if isinstance(details, dict)
    ]

    return AttributionResponse(
        period=period,
        total_return=snapshot.total_return,
        attribution=entries,
    )
