"""Order, fill, position, and trade-approval schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    """Schema for submitting a new order."""

    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    order_type: str = Field(..., pattern="^(market|limit|stop|stop_limit)$")
    quantity: float = Field(..., gt=0)
    limit_price: float | None = Field(None, gt=0)
    stop_price: float | None = Field(None, gt=0)
    time_in_force: str = Field("day", pattern="^(day|gtc|ioc|fok)$")
    strategy: str | None = None
    signal_id: str | None = None


class OrderResponse(BaseModel):
    """Schema for an order acknowledgement or status update."""

    id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    filled_quantity: float = 0.0
    limit_price: float | None = None
    stop_price: float | None = None
    status: str = Field(
        ..., description="'pending', 'open', 'partial', 'filled', 'cancelled', 'rejected'"
    )
    strategy: str | None = None
    signal_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FillResponse(BaseModel):
    """Schema for a single execution fill."""

    id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float = 0.0
    filled_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    """Current open position for a symbol."""

    symbol: str
    side: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealised_pnl: float
    realised_pnl: float
    opened_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TradeApproval(BaseModel):
    """CIO or risk-manager approval / rejection of a proposed trade."""

    order_id: str
    approved: bool
    reason: str | None = None
    approved_by: str = Field(..., description="Username or agent id of the approver")
    approved_at: datetime
