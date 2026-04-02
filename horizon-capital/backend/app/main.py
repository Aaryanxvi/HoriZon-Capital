"""FastAPI entry point for Horizon Capital.

Used for both web API (POSTGRES backend) and desktop app (LOCAL backend).
For the terminal agent, use ``python -m app`` instead.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import StorageBackend, settings
from app.core.logging import get_logger
from app.core.runtime import shutdown, startup

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Warn about insecure defaults
    warnings = settings.validate_production_secrets()
    for w in warnings:
        logger.warning("security_warning", message=w)

    await startup()
    yield
    await shutdown()


app = FastAPI(
    title="Horizon Capital",
    description="Autonomous AI Hedge Fund Platform",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url="/api/redoc" if not settings.is_production else None,
)

# CORS — configurable via CORS_ORIGINS env var
_cors_origins = settings.cors_origin_list
_desktop_port = os.environ.get("HORIZON_DESKTOP_PORT")
if _desktop_port:
    _cors_origins.append(f"http://localhost:{_desktop_port}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    """Add security headers to all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


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
        "version": "0.2.0",
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


# Serve React static files when frontend/dist exists (desktop mode)
_frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    from starlette.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True))
