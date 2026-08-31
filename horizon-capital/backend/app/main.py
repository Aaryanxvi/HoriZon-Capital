"""FastAPI entry point for Horizon Capital.

Used for both web API (POSTGRES backend) and desktop app (LOCAL backend).
For the terminal agent, use ``python -m app`` instead.
"""

import os
import sys
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
    """Application lifecycle: startup and shutdown.

    With ``HORIZON_RUN_AGENTS=1`` (set by the desktop entry point) the agents and
    background workers run inside this process, so the desktop app is the whole
    system rather than a viewer onto an empty database. Default stays off: a bare
    ``uvicorn app.main:app`` behaves exactly as before.
    """
    # Warn about insecure defaults
    warnings = settings.validate_production_secrets()
    for w in warnings:
        logger.warning("security_warning", message=w)

    await startup()

    app.state.orchestrator = None
    app.state.workers = []
    if os.environ.get("HORIZON_RUN_AGENTS") == "1":
        await _start_agents(app)

    try:
        yield
    finally:
        await _stop_agents(app)
        await shutdown()


async def _start_agents(app: FastAPI) -> None:
    """Boot the org chart in-process. Reuses the terminal's worker wiring."""
    # ponytail: `app.__main__` owns worker startup; importing it keeps one
    # definition instead of a second copy that can drift from the terminal.
    from app.__main__ import _start_workers
    from app.core.runtime import get_bus
    from app.llm.provider_registry import provider_registry
    from app.workers.agent_orchestrator import AgentOrchestrator

    provider_registry.auto_register_from_settings()
    orchestrator = AgentOrchestrator(bus=get_bus())
    app.state.orchestrator = orchestrator
    app.state.workers = await _start_workers(orchestrator)
    await orchestrator.start_all()

    # REPL commands like `portfolio`, `signals` and `risk` read dashboard state.
    # Attaching the same dashboard the TUI uses keeps the desktop terminal's
    # answers identical to the CLI's.
    from app.tui.dashboard import TerminalDashboard
    from app.tui.dashboard_feed import attach as attach_dashboard

    dashboard = TerminalDashboard()
    await attach_dashboard(dashboard, orchestrator, get_bus())
    app.state.dashboard = dashboard
    logger.info(
        "desktop_agents_started",
        agents=len(orchestrator.get_agent_statuses()),
        workers=len(app.state.workers),
    )


async def _stop_agents(app: FastAPI) -> None:
    orchestrator = getattr(app.state, "orchestrator", None)
    if orchestrator is None:
        return
    from app.__main__ import _stop_workers

    await orchestrator.stop_all()
    await _stop_workers(getattr(app.state, "workers", []))
    app.state.orchestrator = None
    app.state.dashboard = None


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
from app.api.desktop import router as desktop_router  # noqa: E402
from app.api.websocket import ws_router  # noqa: E402

app.include_router(desktop_router)
app.include_router(ws_router)

# api/v1 is the Postgres/ORM surface — importing it pulls in asyncpg and the ORM
# models, neither of which LOCAL mode has or needs. The desktop router above is
# the LOCAL equivalent.
if settings.storage_backend == StorageBackend.POSTGRES:
    from app.api.v1.router import api_router  # noqa: E402

    app.include_router(api_router, prefix="/api/v1")


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


# Serve the built React app when frontend/dist exists (desktop mode).
# Bundled builds ship it next to the executable, so check there too.
def _find_frontend_dist() -> Path | None:
    candidates = [
        Path(os.environ["HORIZON_FRONTEND_DIST"])
        if os.environ.get("HORIZON_FRONTEND_DIST")
        else None,
        Path(__file__).parent.parent.parent / "frontend" / "dist",
        Path(getattr(sys, "_MEIPASS", ".")) / "frontend",
        Path(sys.executable).parent / "frontend",
    ]
    for path in candidates:
        if path and path.is_dir() and (path / "index.html").is_file():
            return path
    return None


_frontend_dist = _find_frontend_dist()
if _frontend_dist:
    from starlette.responses import FileResponse
    from starlette.staticfiles import StaticFiles

    app.mount(
        "/assets",
        StaticFiles(directory=str(_frontend_dist / "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def spa(full_path: str) -> Response:
        """Serve real files, and index.html for every client-side route.

        Without the fallback, reloading on /portfolio 404s — the router lives in
        the browser and the server has no such file.
        """
        candidate = (_frontend_dist / full_path).resolve()
        if (
            full_path
            and _frontend_dist.resolve() in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
