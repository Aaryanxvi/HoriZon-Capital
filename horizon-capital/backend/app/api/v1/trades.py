"""Trade endpoints: list orders, create order, approve order."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.redis_client import redis_client
from app.dependencies import get_current_user
from app.models.trades import Order, OrderStatus

router = APIRouter(prefix="/trades", tags=["trades"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OrderOut(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    order_type: str
    side: str
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    status: str
    broker: str
    mode: str
    signal_id: UUID | None = None
    debate_id: UUID | None = None
    broker_order_id: str | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    orders: list[OrderOut]
    count: int


class CreateOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    exchange: str = Field(..., min_length=1, max_length=20)
    order_type: str = Field(..., description="MARKET, LIMIT, STOP, STOP_LIMIT")
    side: str = Field(..., description="BUY or SELL")
    quantity: float = Field(..., gt=0)
    limit_price: float | None = None
    stop_price: float | None = None
    signal_id: UUID | None = None
    debate_id: UUID | None = None


class ApproveResponse(BaseModel):
    id: UUID
    status: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=OrderListResponse)
async def list_orders(
    symbol: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> OrderListResponse:
    """List orders with optional symbol and status filters."""
    stmt = select(Order).order_by(Order.created_at.desc())

    if symbol:
        stmt = stmt.where(Order.symbol == symbol)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return OrderListResponse(
        orders=[OrderOut.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> OrderOut:
    """Create a new order. In HUMAN_APPROVAL mode the order starts as PENDING."""
    # Determine broker from mode
    current_mode = await redis_client.get("horizon:system:mode") or settings.system_mode.value
    broker = "PAPER" if "PAPER" in current_mode else "ALPACA"

    # Check kill switch
    kill_switch = await redis_client.get("horizon:risk:kill_switch")
    if kill_switch == "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kill switch is active. Trading is halted.",
        )

    order = Order(
        symbol=body.symbol,
        exchange=body.exchange,
        order_type=body.order_type,
        side=body.side,
        quantity=body.quantity,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        status=OrderStatus.PENDING.value,
        broker=broker,
        mode=current_mode,
        signal_id=body.signal_id,
        debate_id=body.debate_id,
    )
    db.add(order)
    await db.flush()
    await db.refresh(order)

    return OrderOut.model_validate(order)


@router.post("/{order_id}/approve", response_model=ApproveResponse)
async def approve_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> ApproveResponse:
    """Approve a PENDING order, moving it to OPEN status for execution."""
    stmt = select(Order).where(Order.id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found",
        )

    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order is in {order.status} state and cannot be approved",
        )

    order.status = OrderStatus.OPEN.value
    await db.flush()

    # Publish order approval event to Redis for the execution agent
    import orjson

    await redis_client.publish(
        "horizon.order.approved",
        orjson.dumps({"order_id": str(order.id), "symbol": order.symbol}).decode(),
    )

    return ApproveResponse(
        id=order.id,
        status=order.status,
        message="Order approved and queued for execution",
    )
