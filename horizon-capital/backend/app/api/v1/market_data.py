"""Market data endpoints: real-time quotes (Redis), OHLCV history (Postgres), regime."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import redis_client
from app.dependencies import get_current_user
from app.models.market_data import OHLCV
from app.schemas.market_data import (
    NormalizedOHLCV,
    OHLCVResponse,
    QuoteResponse,
    RegimeResponse,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(
    symbol: str,
    _user: dict = Depends(get_current_user),
) -> QuoteResponse:
    """Fetch the latest quote for a symbol from Redis HSET."""
    key = f"horizon:quote:{symbol}"
    data = await redis_client.hgetall(key)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No quote found for symbol {symbol}",
        )

    return QuoteResponse(
        symbol=symbol,
        bid=float(data.get("bid", 0)),
        ask=float(data.get("ask", 0)),
        last=float(data.get("last", 0)),
        volume=float(data.get("volume", 0)),
        timestamp=datetime.fromisoformat(data["timestamp"])
        if "timestamp" in data
        else datetime.now(UTC),
        source=data.get("source"),
    )


@router.get("/ohlcv/{symbol}", response_model=OHLCVResponse)
async def get_ohlcv(
    symbol: str,
    interval: str = Query("1d", description="Bar interval: 1m, 5m, 1h, 1d"),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> OHLCVResponse:
    """Fetch OHLCV bars for a symbol from Postgres."""
    stmt = (
        select(OHLCV)
        .where(OHLCV.symbol == symbol, OHLCV.timeframe == interval)
        .order_by(OHLCV.timestamp.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    bars = [
        NormalizedOHLCV(
            symbol=row.symbol,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=float(row.volume),
            timestamp=row.timestamp,
            interval=row.timeframe,
        )
        for row in reversed(rows)  # return chronological order
    ]

    return OHLCVResponse(
        symbol=symbol,
        interval=interval,
        bars=bars,
        count=len(bars),
    )


@router.get("/regime/current", response_model=RegimeResponse)
async def get_current_regime(
    _user: dict = Depends(get_current_user),
) -> RegimeResponse:
    """Return the current market regime classification from Redis."""
    key = "horizon:regime:current"
    data = await redis_client.hgetall(key)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No regime data available",
        )

    # Parse features JSON stored as string
    import orjson

    features_raw = data.get("features", "{}")
    features = orjson.loads(features_raw) if isinstance(features_raw, str) else features_raw

    return RegimeResponse(
        regime=data.get("regime", "unknown"),
        confidence=float(data.get("confidence", 0.0)),
        features=features,
        timestamp=datetime.fromisoformat(data["timestamp"])
        if "timestamp" in data
        else datetime.now(UTC),
        model_version=data.get("model_version"),
    )
