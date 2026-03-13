"""Risk endpoints: metrics, limits, and kill-switch control."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import redis_client
from app.dependencies import get_current_user
from app.models.risk import RiskLimit, RiskMetric

router = APIRouter(prefix="/risk", tags=["risk"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RiskMetricOut(BaseModel):
    id: UUID
    var_1d_95: float
    var_1d_99: float
    cvar_1d_95: float
    max_drawdown: float
    current_drawdown: float
    beta_india: float
    beta_us: float
    sharpe_30d: float
    kill_switch_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskLimitOut(BaseModel):
    id: UUID
    limit_name: str
    threshold: float
    unit: str
    action_on_breach: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskLimitListResponse(BaseModel):
    limits: list[RiskLimitOut]
    count: int


class KillSwitchResponse(BaseModel):
    kill_switch_active: bool
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/metrics", response_model=RiskMetricOut)
async def get_risk_metrics(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> RiskMetricOut:
    """Return the most recent risk metrics snapshot."""
    stmt = (
        select(RiskMetric)
        .order_by(RiskMetric.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    metric = result.scalar_one_or_none()

    if metric is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No risk metrics available",
        )

    return RiskMetricOut.model_validate(metric)


@router.get("/limits", response_model=RiskLimitListResponse)
async def list_risk_limits(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> RiskLimitListResponse:
    """List all configured risk limits."""
    stmt = select(RiskLimit).order_by(RiskLimit.limit_name)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return RiskLimitListResponse(
        limits=[RiskLimitOut.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.post("/kill-switch/activate", response_model=KillSwitchResponse)
async def activate_kill_switch(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> KillSwitchResponse:
    """Activate the kill switch: halt all trading immediately."""
    # Set flag in Redis for fast cross-service check
    await redis_client.set("horizon:risk:kill_switch", "active")

    # Persist in latest risk metric row
    stmt = select(RiskMetric).order_by(RiskMetric.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    metric = result.scalar_one_or_none()
    if metric is not None:
        metric.kill_switch_active = True
        await db.flush()

    # Publish kill-switch event
    await redis_client.publish(
        "horizon.risk.kill_switch",
        '{"active": true}',
    )

    return KillSwitchResponse(
        kill_switch_active=True,
        message="Kill switch activated. All trading halted.",
    )


@router.post("/kill-switch/deactivate", response_model=KillSwitchResponse)
async def deactivate_kill_switch(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> KillSwitchResponse:
    """Deactivate the kill switch: resume trading."""
    await redis_client.set("horizon:risk:kill_switch", "inactive")

    stmt = select(RiskMetric).order_by(RiskMetric.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    metric = result.scalar_one_or_none()
    if metric is not None:
        metric.kill_switch_active = False
        await db.flush()

    await redis_client.publish(
        "horizon.risk.kill_switch",
        '{"active": false}',
    )

    return KillSwitchResponse(
        kill_switch_active=False,
        message="Kill switch deactivated. Trading resumed.",
    )
