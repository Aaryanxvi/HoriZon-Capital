"""Aggregate all v1 API routers into a single api_router."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.market_data import router as market_data_router
from app.api.v1.signals import router as signals_router
from app.api.v1.trades import router as trades_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.risk import router as risk_router
from app.api.v1.agents import router as agents_router
from app.api.v1.debate import router as debate_router
from app.api.v1.narratives import router as narratives_router
from app.api.v1.performance import router as performance_router
from app.api.v1.cio import router as cio_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(market_data_router)
api_router.include_router(signals_router)
api_router.include_router(trades_router)
api_router.include_router(portfolio_router)
api_router.include_router(risk_router)
api_router.include_router(agents_router)
api_router.include_router(debate_router)
api_router.include_router(narratives_router)
api_router.include_router(performance_router)
api_router.include_router(cio_router)
