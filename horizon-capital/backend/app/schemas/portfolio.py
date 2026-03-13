"""Portfolio-level schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class PositionSummary(BaseModel):
    """Condensed view of a single position within the portfolio."""

    symbol: str
    side: str
    quantity: float
    avg_entry_price: float
    market_value: float
    weight: float = Field(..., ge=0.0, le=1.0, description="Position weight as a fraction of NAV")
    unrealised_pnl: float
    realised_pnl: float

    model_config = {"from_attributes": True}


class PortfolioSummary(BaseModel):
    """Top-level portfolio snapshot."""

    nav: float = Field(..., description="Net asset value")
    cash: float
    total_exposure: float
    long_exposure: float
    short_exposure: float
    gross_leverage: float
    net_leverage: float
    positions: list[PositionSummary]
    position_count: int
    timestamp: datetime
    as_of_date: str | None = Field(None, description="Trading date in YYYY-MM-DD format")

    model_config = {"from_attributes": True}
