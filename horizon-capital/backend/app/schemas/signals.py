"""Trading signal schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class SignalResponse(BaseModel):
    """A single trading signal emitted by a strategy agent."""

    id: str
    symbol: str
    direction: str = Field(..., description="'long' or 'short'")
    strength: float = Field(
        ..., ge=-1.0, le=1.0, description="Signal strength, negative for short bias"
    )
    strategy: str = Field(..., description="Name of the originating strategy")
    regime: str | None = None
    meta: dict[str, float | str] = Field(
        default_factory=dict, description="Arbitrary strategy metadata"
    )
    created_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class SignalListResponse(BaseModel):
    """Paginated list of trading signals."""

    signals: list[SignalResponse]
    total: int
    page: int = 1
    page_size: int = 50
