"""FastAPI entry point for Horizon Capital.

This module is only used when running as a web API (POSTGRES backend).
For the terminal agent, use ``python -m app`` instead.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import StorageBackend, settings
from app.core.logging import get_logger, setup_logging
from app.core.runtime import get_bus, shutdown, startup

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    await startup()
    yield
    await shutdown()


app = FastAPI(
    title="Horizon Capital",
    description="Autonomous AI Hedge Fund Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
from app.api.v1.router import api_router  # noqa: E402
from app.api.websocket import ws_router  # noqa: E402

app.include_router(api_router, prefix="/api/v1")
app.include_router(ws_router)


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    status_info = {
        "status": "healthy",
        "mode": settings.system_mode.value,
        "storage": settings.storage_backend.value,
        "version": "0.1.0",
    }

    if settings.storage_backend == StorageBackend.POSTGRES:
        try:
            from app.core.redis_client import redis_client
            await redis_client.ping()
            status_info["redis"] = "connected"
        except Exception:
            status_info["redis"] = "disconnected"
            status_info["status"] = "degraded"

    return status_info
