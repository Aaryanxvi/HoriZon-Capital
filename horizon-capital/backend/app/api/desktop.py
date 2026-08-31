"""Desktop API — read models for the Electron UI, actions via the REPL handler.

Two rules keep this file honest:

1. **Reads** hit the same SQLite tables and KV keys the terminal reads. They work
   in LOCAL mode with no Postgres/Redis, unlike ``api/v1`` (ORM + asyncpg).
2. **Writes go through `CommandHandler`** — the exact code path the terminal
   uses. A button in the UI and a typed command cannot drift apart, and no
   trading logic is duplicated here.

Mounted at ``/api/desktop``. The desktop backend binds 127.0.0.1 only, so these
endpoints are unauthenticated like the rest of LOCAL mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from rich.console import Console
from sqlalchemy import text

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(result) -> list[dict[str, Any]]:
    """SQLAlchemy result -> list of plain dicts with stringified timestamps."""
    out: list[dict[str, Any]] = []
    for row in result.fetchall():
        item = dict(row._mapping)
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        out.append(item)
    return out


async def _query(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Run a read-only query against the active storage backend."""
    from app.core.runtime import get_session_factory

    async with get_session_factory()() as session:
        result = await session.execute(text(sql), params or {})
        return _rows(result)


async def _kv():
    from app.core.kv_store import get_kv_store

    return get_kv_store()


def _f(value: Any, default: float = 0.0) -> float:
    """Best-effort float — KV values are strings and may be absent."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _orchestrator(request: Request):
    """The running orchestrator, or None when the API runs without agents."""
    return getattr(request.app.state, "orchestrator", None)


def render_markup(markup: str) -> dict[str, str]:
    """Render Rich console markup to both plain text and standalone HTML.

    The REPL's output is Rich markup, not data. Rather than re-implement every
    command's formatting for the browser, render it the way the terminal would
    and ship both forms: `text` for copy/paste, `html` for the colours.
    """
    console = Console(
        file=io.StringIO(),
        record=True,
        width=110,
        color_system="truecolor",
        force_terminal=False,
        highlight=False,
        soft_wrap=False,
    )
    console.print(markup)
    return {
        # clear=False: export_text() would otherwise consume the recorded
        # segments and export_html() would return an empty document.
        "text": console.export_text(clear=False),
        "html": console.export_html(
            inline_styles=True,
            code_format='<pre style="white-space:pre-wrap;word-break:break-word">{code}</pre>',
        ),
    }


# ---------------------------------------------------------------------------
# Live event hub — one bus subscription for the whole process
# ---------------------------------------------------------------------------

class _EventHub:
    """Fan bus messages out to every connected websocket.

    One subscription for the process lifetime: ``MemoryBus.unsubscribe`` drops
    *all* handlers on a channel, so per-client subscribe/unsubscribe would let a
    disconnecting client silence everyone else.
    """

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue] = set()
        self._subscribed = False
        self._recent: list[dict] = []

    async def ensure_subscribed(self) -> None:
        if self._subscribed:
            return
        from app.core.runtime import get_bus

        bus = get_bus()
        await bus.subscribe("horizon.*", self._on_message)
        self._subscribed = True

    async def _on_message(self, message) -> None:
        try:
            event = {
                "channel": message.channel,
                "type": str(getattr(message.message_type, "value", message.message_type)),
                "sender": message.sender_id,
                "timestamp": getattr(message, "timestamp", None),
                "payload": message.payload,
            }
            if hasattr(event["timestamp"], "isoformat"):
                event["timestamp"] = event["timestamp"].isoformat()
            json.dumps(event, default=str)  # reject anything unserialisable early
        except Exception:
            return

        self._recent.append(event)
        del self._recent[:-200]

        for queue in list(self._clients):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled client must not back-pressure the trading loop.
                pass

    def register(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._clients.add(queue)
        return queue

    def unregister(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)

    @property
    def recent(self) -> list[dict]:
        return list(self._recent)


hub = _EventHub()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    """Everything the home screen needs, in one round trip."""
    kv = await _kv()

    cash_usd = _f(await kv.get("horizon:cash:usd"))
    cash_inr = _f(await kv.get("horizon:cash:inr"))
    nav = _f(await kv.get("horizon:portfolio:nav"))
    halted = (await kv.get("horizon:system:halted")) == "1"
    kill_switch = (await kv.get("horizon:system:kill_switch")) == "1"
    halt_reason = await kv.get("horizon:system:halt_reason")
    regime = await kv.get("horizon:regime:current")

    positions = await _query(
        "SELECT symbol, quantity, current_price, unrealized_pnl, currency "
        "FROM positions WHERE quantity != 0"
    )
    equity_value = sum(
        abs(_f(p["quantity"]) * _f(p["current_price"])) for p in positions
    )
    unrealized = sum(_f(p["unrealized_pnl"]) for p in positions)

    if nav <= 0:
        nav = cash_usd + equity_value

    # Day P&L: newest snapshot vs the oldest one from the last 24h.
    day_pnl = 0.0
    day_pnl_pct = 0.0
    curve = await _query(
        "SELECT total_value, created_at FROM portfolio_snapshots "
        "ORDER BY created_at DESC LIMIT 400"
    )
    if len(curve) >= 2:
        latest = _f(curve[0]["total_value"])
        opening = _f(curve[min(len(curve) - 1, 95)]["total_value"])
        if opening > 0:
            day_pnl = latest - opening
            day_pnl_pct = day_pnl / opening * 100

    perf = await _query(
        "SELECT period, total_return, sharpe_ratio, max_drawdown, win_rate, "
        "total_trades FROM performance_snapshots ORDER BY created_at DESC LIMIT 1"
    )
    risk = await _query(
        "SELECT var_1d_95, var_1d_99, cvar_1d_95, max_drawdown, current_drawdown, "
        "kill_switch_active FROM risk_metrics ORDER BY created_at DESC LIMIT 1"
    )

    orch = _orchestrator(request)
    agent_statuses = orch.get_agent_statuses() if orch else {}
    agents_running = sum(
        1 for s in agent_statuses.values() if str(s.get("status", "")).upper() == "RUNNING"
    )

    from app.llm.provider_registry import provider_registry

    initial_capital = float(settings.initial_capital_usd)
    return {
        "nav": nav,
        "cash_usd": cash_usd,
        "cash_inr": cash_inr,
        "equity_value": equity_value,
        "unrealized_pnl": unrealized,
        "total_return_pct": (
            (nav - initial_capital) / initial_capital * 100 if initial_capital else 0.0
        ),
        "initial_capital": initial_capital,
        "day_pnl": day_pnl,
        "day_pnl_pct": day_pnl_pct,
        "positions_count": len(positions),
        "system_mode": settings.system_mode.value,
        "cio_mode": settings.cio_mode.value,
        "storage": settings.storage_backend.value,
        "halted": halted,
        "halt_reason": halt_reason,
        "kill_switch": kill_switch or bool(risk and risk[0].get("kill_switch_active")),
        "regime": regime,
        "agents_running": agents_running,
        "agents_total": len(agent_statuses),
        "agents_live": bool(orch),
        "llm_providers": provider_registry.list_available(),
        "performance": perf[0] if perf else None,
        "risk": risk[0] if risk else None,
    }


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@router.get("/positions")
async def positions() -> dict[str, Any]:
    rows = await _query(
        "SELECT symbol, exchange, side, quantity, avg_entry_price, current_price, "
        "unrealized_pnl, realized_pnl, weight_pct, currency, stop_loss_price, "
        "updated_at FROM positions WHERE quantity != 0 ORDER BY symbol"
    )
    for row in rows:
        qty, price = _f(row["quantity"]), _f(row["current_price"])
        entry = _f(row["avg_entry_price"])
        row["market_value"] = qty * price
        row["return_pct"] = ((price - entry) / entry * 100) if entry else 0.0
    return {"positions": rows, "count": len(rows)}


@router.get("/equity-curve")
async def equity_curve(limit: int = Query(500, ge=2, le=5000)) -> dict[str, Any]:
    rows = await _query(
        "SELECT total_value, cash_usd, equity_value, created_at "
        "FROM portfolio_snapshots ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
    )
    return {"points": list(reversed(rows))}


# ---------------------------------------------------------------------------
# Trading
# ---------------------------------------------------------------------------

@router.get("/orders")
async def orders(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    rows = await _query(
        "SELECT id, symbol, exchange, order_type, side, quantity, limit_price, "
        "status, broker, mode, rejection_reason, created_at "
        "FROM orders ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
    )
    return {"orders": rows, "count": len(rows)}


@router.get("/fills")
async def fills(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    rows = await _query(
        "SELECT f.id, f.order_id, o.symbol, o.side, o.exchange, f.filled_qty, "
        "f.fill_price, f.commission, f.slippage, f.filled_at "
        "FROM fills f LEFT JOIN orders o ON f.order_id = o.id "
        "ORDER BY f.filled_at DESC LIMIT :limit",
        {"limit": limit},
    )
    for row in rows:
        row["notional"] = _f(row["filled_qty"]) * _f(row["fill_price"])
    return {"fills": rows, "count": len(rows)}


@router.get("/pending")
async def pending(request: Request) -> dict[str, Any]:
    """Orders waiting on a human decision (HUMAN_APPROVAL mode)."""
    rows = await _query(
        "SELECT id, payload, created_at FROM pending_approvals ORDER BY created_at"
    )
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        out.append({"order_id": row["id"], "created_at": row["created_at"], **payload})
    return {"pending": out, "count": len(out)}


@router.get("/signals")
async def signals(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = await _query(
        "SELECT signal_id, agent_id, symbol, direction, strength, confidence, "
        "strategy_name, regime, created_at FROM signals "
        "ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
    )
    return {"signals": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Agents, debates, risk, performance
# ---------------------------------------------------------------------------

@router.get("/agents")
async def agents(request: Request) -> dict[str, Any]:
    orch = _orchestrator(request)
    if not orch:
        return {"departments": [], "agents": [], "workers": [], "live": False}

    by_dept = orch.get_agents_by_department()
    return {
        "live": True,
        "departments": orch.get_department_statuses(),
        "agents": [
            {**agent, "department": dept}
            for dept, agents_in_dept in by_dept.items()
            for agent in agents_in_dept
        ],
        "workers": [
            {"name": name, **status}
            for name, status in orch.get_worker_statuses().items()
        ],
    }


@router.get("/debates")
async def debates(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    rows = await _query(
        "SELECT id, symbol, proposed_action, proposed_quantity, status, "
        "final_decision, consensus_score, total_rounds, reason, created_at "
        "FROM debate_sessions ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
    )
    return {"debates": rows, "count": len(rows)}


@router.get("/debates/{session_id}")
async def debate_detail(session_id: str) -> dict[str, Any]:
    session = await _query(
        "SELECT * FROM debate_sessions WHERE id = :id", {"id": session_id}
    )
    arguments = await _query(
        "SELECT agent_id, role, argument, vote, confidence, round_number, created_at "
        "FROM debate_arguments WHERE session_id = :id "
        "ORDER BY round_number, created_at",
        {"id": session_id},
    )
    return {"session": session[0] if session else None, "arguments": arguments}


@router.get("/risk")
async def risk() -> dict[str, Any]:
    kv = await _kv()
    latest = await _query(
        "SELECT * FROM risk_metrics ORDER BY created_at DESC LIMIT 1"
    )
    history = await _query(
        "SELECT var_1d_95, current_drawdown, max_drawdown, created_at "
        "FROM risk_metrics ORDER BY created_at DESC LIMIT 200"
    )
    return {
        "latest": latest[0] if latest else None,
        "history": list(reversed(history)),
        "limits": {
            "max_drawdown_pct": settings.risk_max_drawdown_pct,
            "max_position_pct": settings.risk_max_position_pct,
            "max_leverage": settings.risk_max_leverage,
            "var_limit_pct": settings.risk_var_limit_pct,
            "daily_loss_limit_pct": getattr(settings, "risk_daily_loss_limit_pct", None),
        },
        "halted": (await kv.get("horizon:system:halted")) == "1",
        "halt_reason": await kv.get("horizon:system:halt_reason"),
    }


@router.get("/performance")
async def performance() -> dict[str, Any]:
    rows = await _query(
        "SELECT period, total_return, annualized_return, sharpe_ratio, sortino_ratio, "
        "calmar_ratio, max_drawdown, win_rate, profit_factor, alpha_india, alpha_us, "
        "total_trades, attribution, created_at FROM performance_snapshots "
        "ORDER BY created_at DESC LIMIT 50"
    )
    by_period: dict[str, dict] = {}
    for row in rows:
        by_period.setdefault(str(row["period"]), row)
    return {"periods": by_period, "latest": rows[0] if rows else None}


@router.get("/alerts")
async def alerts(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = await _query(
        "SELECT id, rule_name, severity, title, message, acknowledged, created_at "
        "FROM alert_history ORDER BY created_at DESC LIMIT :limit",
        {"limit": limit},
    )
    return {"alerts": rows, "count": len(rows)}


@router.get("/watchlist")
async def watchlist() -> dict[str, Any]:
    """Latest price and 24h move for every symbol the system tracks."""
    kv = await _kv()
    out = []
    for symbol in settings.all_symbols:
        price = _f(await kv.get(f"horizon:price:{symbol}"))
        prev = _f(await kv.get(f"horizon:price:prev_close:{symbol}"))
        out.append({
            "symbol": symbol,
            "price": price,
            "prev_close": prev,
            "change_pct": ((price - prev) / prev * 100) if prev else 0.0,
        })
    return {"watchlist": out}


# ---------------------------------------------------------------------------
# Configuration (read) — writes go through /command
# ---------------------------------------------------------------------------

def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return f"***{value[-4:]}"


@router.get("/config")
async def config(request: Request) -> dict[str, Any]:
    from app.llm.provider_registry import provider_registry

    return {
        "system_mode": settings.system_mode.value,
        "cio_mode": settings.cio_mode.value,
        "storage_backend": settings.storage_backend.value,
        "initial_capital_usd": settings.initial_capital_usd,
        "initial_capital_inr": settings.initial_capital_inr,
        "universe": {
            "india": settings.india_symbols,
            "us": settings.us_symbols,
            "crypto": settings.crypto_symbols,
        },
        "risk": {
            "max_drawdown_pct": settings.risk_max_drawdown_pct,
            "max_position_pct": settings.risk_max_position_pct,
            "max_leverage": settings.risk_max_leverage,
            "var_limit_pct": settings.risk_var_limit_pct,
            "risk_free_rate": settings.risk_free_rate,
        },
        "sleeves": {
            "crypto": {
                "enabled": settings.crypto_sleeve_enabled,
                "weight": settings.crypto_sleeve_weight,
                "discovery": settings.crypto_discovery_enabled,
                "discovery_top_n": settings.crypto_discovery_top_n,
            },
            "polymarket": {
                "enabled": settings.polymarket_sleeve_enabled,
                "weight": settings.polymarket_sleeve_weight,
                "discovery": settings.polymarket_discovery_enabled,
                "discovery_top_n": settings.polymarket_discovery_top_n,
                "markets": settings.polymarket_markets,
            },
        },
        "llm": {
            "providers": provider_registry.list_available(),
            "front_office": settings.ai_front_office,
            "middle_office": settings.ai_middle_office,
            "back_office": settings.ai_back_office,
            "executive": settings.ai_executive,
        },
        "keys": {
            "anthropic": _mask(settings.anthropic_api_key),
            "openai": _mask(settings.openai_api_key),
            "google": _mask(settings.google_api_key),
            "alpaca": _mask(settings.alpaca_api_key),
            "newsapi": _mask(settings.newsapi_api_key),
            "telegram": _mask(settings.telegram_bot_token),
        },
        "version": "0.2.0",
    }


# ---------------------------------------------------------------------------
# Controls — halt, mode, settings, engine, onboarding
# ---------------------------------------------------------------------------

# Only these may be written from the UI. Anything not listed here (storage
# backend, secrets that auto-generate, ports) stays a file-level decision.
EDITABLE_ENV: dict[str, str] = {
    "SYSTEM_MODE": "system_mode",
    "CIO_MODE": "cio_mode",
    "INITIAL_CAPITAL_USD": "initial_capital_usd",
    "INITIAL_CAPITAL_INR": "initial_capital_inr",
    "US_SYMBOLS": "us_symbols",
    "INDIA_SYMBOLS": "india_symbols",
    "CRYPTO_SYMBOLS": "crypto_symbols",
    "RISK_MAX_DRAWDOWN_PCT": "risk_max_drawdown_pct",
    "RISK_MAX_POSITION_PCT": "risk_max_position_pct",
    "RISK_MAX_LEVERAGE": "risk_max_leverage",
    "RISK_VAR_LIMIT_PCT": "risk_var_limit_pct",
    "RISK_DAILY_LOSS_LIMIT_PCT": "risk_daily_loss_limit_pct",
    "RISK_FREE_RATE": "risk_free_rate",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "OPENAI_API_KEY": "openai_api_key",
    "GOOGLE_API_KEY": "google_api_key",
    "ALPACA_API_KEY": "alpaca_api_key",
    "ALPACA_API_SECRET": "alpaca_api_secret",
    "NEWSAPI_API_KEY": "newsapi_api_key",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "AI_FRONT_OFFICE": "ai_front_office",
    "AI_MIDDLE_OFFICE": "ai_middle_office",
    "AI_BACK_OFFICE": "ai_back_office",
    "AI_EXECUTIVE": "ai_executive",
    "DEBATE_MODEL": "debate_model",
}

# Changing these mid-flight does not reach the agent that read them at
# construction; the UI says so instead of pretending the change took effect.
NEEDS_RESTART = {
    "US_SYMBOLS",
    "INDIA_SYMBOLS",
    "CRYPTO_SYMBOLS",
    "INITIAL_CAPITAL_USD",
    "INITIAL_CAPITAL_INR",
    "CIO_MODE",
}


def _env_path() -> str:
    from pathlib import Path

    # backend/.env — the file pydantic-settings actually reads.
    return str(Path(__file__).resolve().parents[2] / ".env")


def _apply_env(key: str, value: str) -> str | None:
    """Persist one setting to .env and mirror it onto the live Settings object.

    Returns an error string, or None on success. Values are coerced through the
    field's own type so a bad number is rejected here rather than at the point
    some agent tries to use it.
    """
    attr = EDITABLE_ENV.get(key)
    if attr is None:
        return f"{key} is not editable from the app"

    field = type(settings).model_fields.get(attr)
    if field is None:
        return f"{key} has no matching setting"

    from pydantic import TypeAdapter, ValidationError

    try:
        coerced = TypeAdapter(field.annotation).validate_python(value)
    except ValidationError as exc:
        return f"{key}: {exc.errors()[0].get('msg', 'invalid value')}"

    from app.tui.settings_panel import _write_env_key

    _write_env_key(_env_path(), key, str(value))
    setattr(settings, attr, coerced)
    return None


@router.post("/control/settings")
async def update_settings(request: Request) -> dict[str, Any]:
    """Write settings to .env and apply what can safely change at runtime."""
    body = await request.json()
    updates = body.get("updates") or {}
    if not isinstance(updates, dict):
        return {"ok": False, "errors": ["updates must be an object"]}

    applied: list[str] = []
    errors: list[str] = []
    for key, value in updates.items():
        error = _apply_env(str(key).upper(), "" if value is None else str(value))
        if error:
            errors.append(error)
        else:
            applied.append(str(key).upper())

    if any(k.endswith("_API_KEY") or k == "DEBATE_MODEL" for k in applied):
        # New keys should light up the providers without a restart.
        from app.llm.provider_registry import provider_registry

        with contextlib.suppress(Exception):
            provider_registry.auto_register_from_settings()

    if "SYSTEM_MODE" in applied:
        kv = await _kv()
        await kv.set("horizon:system:mode", settings.system_mode.value)

    return {
        "ok": not errors,
        "applied": applied,
        "errors": errors,
        "restart_required": sorted(set(applied) & NEEDS_RESTART),
    }


@router.post("/control/halt")
async def set_halt(request: Request) -> dict[str, Any]:
    """Halt or resume trading — the same flag the risk agent's kill switch sets.

    Halting is immediate: the execution agent checks this key before every
    order. Resuming is deliberate, because the risk agent will not clear a
    kill switch on its own.
    """
    body = await request.json()
    halted = bool(body.get("halted"))
    reason = str(body.get("reason") or ("Halted from the desktop app" if halted else ""))

    kv = await _kv()
    await kv.set("horizon:system:halted", "1" if halted else "0")
    await kv.set("horizon:system:kill_switch", "1" if halted else "0")
    if halted:
        await kv.set("horizon:system:halt_reason", reason)
    else:
        await kv.set("horizon:system:halt_reason", "")
        # Acknowledge, so the risk agent does not treat the old breach as new.
        await kv.set("horizon:system:halted:ack", "1")

    from app.core.messaging import AgentMessage, MessageType
    from app.core.runtime import get_bus

    with contextlib.suppress(Exception):
        await get_bus().publish(
            AgentMessage(
                channel="horizon.risk.alert",
                message_type=MessageType.RISK_ALERT,
                sender_id="desktop-ui",
                payload={
                    "action": "KILL_SWITCH_TRIGGERED" if halted else "KILL_SWITCH_CLEARED",
                    "severity": "CRITICAL" if halted else "INFO",
                    "message": reason or "Trading resumed from the desktop app",
                },
            )
        )

    logger.warning("desktop_halt_toggled", halted=halted, reason=reason)
    return {"ok": True, "halted": halted, "reason": reason}


@router.post("/control/engine")
async def control_engine(request: Request) -> dict[str, Any]:
    """Start, stop or restart the agents without closing the app.

    Stopping leaves the API and the database up, so the UI still shows the book
    — it just stops acting on it.
    """
    body = await request.json()
    action = str(body.get("action") or "").lower()
    if action not in {"start", "stop", "restart"}:
        return {"ok": False, "error": "action must be start, stop or restart"}

    app = request.app
    from app.main import _start_agents, _stop_agents

    if action in {"stop", "restart"}:
        await _stop_agents(app)
    if action in {"start", "restart"}:
        if getattr(app.state, "orchestrator", None) is None:
            await _start_agents(app)

    orchestrator = getattr(app.state, "orchestrator", None)
    # A new orchestrator means the cached handler points at a dead one.
    global _shared_handler  # noqa: PLW0603
    _shared_handler = None

    return {
        "ok": True,
        "action": action,
        "running": orchestrator is not None,
        "agents": len(orchestrator.get_agent_statuses()) if orchestrator else 0,
    }


@router.get("/onboarding")
async def onboarding_state() -> dict[str, Any]:
    """What first-run setup still needs, so the app can ask for exactly that."""
    import os
    from pathlib import Path

    env_exists = Path(_env_path()).is_file()
    has_llm = any(
        [settings.anthropic_api_key, settings.openai_api_key, settings.google_api_key]
    )
    return {
        "env_exists": env_exists,
        "completed": env_exists and os.environ.get("HORIZON_ONBOARDED") != "0" and has_llm,
        "has_llm_key": has_llm,
        "has_broker_key": bool(settings.alpaca_api_key),
        "system_mode": settings.system_mode.value,
        "cio_mode": settings.cio_mode.value,
        "initial_capital_usd": settings.initial_capital_usd,
        "universe": {
            "us": settings.us_symbols,
            "india": settings.india_symbols,
            "crypto": settings.crypto_symbols,
        },
        "missing": [
            name
            for name, value in (
                ("LLM API key (debates, CIO, sentiment)", has_llm),
                ("Alpaca key (live prices and real execution)", settings.alpaca_api_key),
            )
            if not value
        ],
    }


# ---------------------------------------------------------------------------
# Commands — the same handler the terminal drives
# ---------------------------------------------------------------------------

_HANDLER_LOCK = asyncio.Lock()
_shared_handler = None


async def _get_handler(request: Request):
    """One CommandHandler for HTTP callers, wired to the live orchestrator."""
    global _shared_handler  # noqa: PLW0603
    async with _HANDLER_LOCK:
        if _shared_handler is None:
            from app.tui.commands import CommandHandler

            _shared_handler = CommandHandler(
                dashboard=getattr(request.app.state, "dashboard", None),
                orchestrator=_orchestrator(request),
            )
            await _wire_cio(_shared_handler, _orchestrator(request))
        return _shared_handler


async def _wire_cio(handler, orchestrator) -> None:
    """Give the handler the CIO agent so `cio ...` works, exactly as in the TUI."""
    from app.config import CIOMode

    if not orchestrator or settings.cio_mode != CIOMode.AI:
        return
    with contextlib.suppress(Exception):
        cio_agent = orchestrator.get_agent("cio-agent-1")
        if cio_agent:
            handler.set_cio_agent(cio_agent)


async def _run_command(handler, line: str) -> dict[str, Any]:
    """Execute one REPL line and package the result for the UI."""
    line = (line or "").strip()
    if not line:
        return {"text": "", "html": "", "command": line}

    # Three commands are terminal-UI affordances rather than system actions. The
    # desktop has its own equivalents, so map them instead of failing: every
    # other command reaches the handler untouched.
    verb = line.split()[0].lower()
    if verb in {"quit", "exit"}:
        return {
            "text": "Close the window to quit — the engine keeps running until then.",
            "html": "Close the window to quit — the engine keeps running until then.",
            "command": line,
        }
    if verb == "dashboard":
        return {
            "text": "Opening the live dashboard.",
            "html": "Opening the live dashboard.",
            "command": line,
            "action": "open_dashboard",
        }

    try:
        result = await handler.handle(line)
    except Exception as exc:  # a bad command must not kill the panel
        logger.warning("desktop_command_error", command=line, error=str(exc))
        return {
            "text": f"Command failed: {exc}",
            "html": f"<span style='color:#b91c1c'>Command failed: {exc}</span>",
            "command": line,
            "error": True,
        }

    if result == "__OPEN_SETTINGS__":
        return {
            "text": "Settings live on the Settings page in this app.",
            "html": "Settings live on the Settings page in this app.",
            "command": line,
            "action": "open_settings",
        }
    if result is None:
        return {"text": "", "html": "", "command": line}
    return {**render_markup(result), "command": line}


@router.post("/command")
async def command(request: Request) -> dict[str, Any]:
    body = await request.json()
    handler = await _get_handler(request)
    return await _run_command(handler, body.get("command", ""))


@router.get("/commands")
async def command_list() -> dict[str, Any]:
    """Command vocabulary for the terminal's autocomplete."""
    return {
        "commands": [
            "help", "status", "brief", "dashboard", "portfolio", "positions",
            "orders", "orders all", "signals", "trades", "journal", "journal why",
            "pnl", "backtest", "backtest results", "risk", "sentiment", "debate",
            "debate why", "agents", "health", "doctor", "performance", "report",
            "config", "pending", "approve", "reject", "cio", "cio why",
            "cio confirm halt", "watchlist", "watchlist add", "watchlist remove",
            "buy", "sell", "strategy", "strategy status", "sleeve", "sleeve on",
            "sleeve off", "sleeve weight", "pm", "pm add", "pm remove",
            "pm auto on", "pm auto off", "pm scan", "crypto", "crypto auto on",
            "crypto auto off", "crypto scan", "model", "models", "settings",
        ]
    }


# ---------------------------------------------------------------------------
# Websockets
# ---------------------------------------------------------------------------

@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    """Push every bus message to the UI so views update without polling."""
    await websocket.accept()
    await hub.ensure_subscribed()
    queue = hub.register()
    try:
        await websocket.send_json({"channel": "__hello__", "payload": {"ok": True}})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        hub.unregister(queue)


@router.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket) -> None:
    """A real REPL over a socket: same handler, same commands, same output."""
    await websocket.accept()
    from app.tui.commands import CommandHandler

    orchestrator = getattr(websocket.app.state, "orchestrator", None)
    handler = CommandHandler(
        dashboard=getattr(websocket.app.state, "dashboard", None),
        orchestrator=orchestrator,
    )
    await _wire_cio(handler, orchestrator)

    try:
        while True:
            raw = await websocket.receive_text()
            result = await _run_command(handler, raw)
            await websocket.send_json(result)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
