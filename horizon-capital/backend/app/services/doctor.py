# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-622A487CAD69
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""System doctor: self-check all subsystems (db, bus, LLM, data, alerts, broker)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text


def _get_session_factory():
    from app.core.runtime import get_session_factory

    return get_session_factory()


def _render(name: str, status: str, detail: str) -> str:
    if status == "ok":
        return f"[green]✓[/green] {name:<22} {detail}"
    if status == "warn":
        return f"[yellow]⚠[/yellow] {name:<22} [yellow]{detail}[/yellow]"
    return f"[red]✗[/red] {name:<22} [red]{detail}[/red]"


async def _check_storage() -> tuple[str, str, str]:
    from app.config import settings

    async with _get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    return ("storage", "ok", f"{settings.storage_backend} — db reachable")


async def _check_bus() -> tuple[str, str, str]:
    from app.core.runtime import get_bus

    bus = get_bus()
    return ("bus", "ok", type(bus).__name__)


async def _check_llm_keys() -> tuple[str, str, str]:
    from app.config import settings

    providers = []
    if settings.anthropic_api_key:
        providers.append("claude")
    if settings.openai_api_key:
        providers.append("openai")
    if settings.google_api_key:
        providers.append("gemini")

    if not providers:
        return (
            "llm keys",
            "warn",
            "no LLM keys — debates auto-approve (auto-REJECT in FULLY_AUTONOMOUS)",
        )
    return ("llm keys", "ok", ", ".join(providers))


async def _check_market_data() -> tuple[str, str, str]:
    async with _get_session_factory()() as session:
        result = await session.execute(text("SELECT COUNT(*) AS n FROM ohlcv"))
        total = result.fetchone().n

        result = await session.execute(
            text("SELECT COUNT(*) AS n FROM ohlcv WHERE symbol = 'SPY'")
        )
        spy_count = result.fetchone().n
        if spy_count == 0:
            result = await session.execute(
                text("SELECT COUNT(*) AS n FROM ohlcv WHERE symbol LIKE 'SPY%'")
            )
            spy_count = result.fetchone().n

        result = await session.execute(
            text(
                "SELECT timestamp FROM ohlcv WHERE symbol = 'SPY' "
                "ORDER BY timestamp DESC LIMIT 1"
            )
        )
        row = result.fetchone()
        if row is None:
            result = await session.execute(
                text(
                    "SELECT timestamp FROM ohlcv WHERE symbol LIKE 'SPY%' "
                    "ORDER BY timestamp DESC LIMIT 1"
                )
            )
            row = result.fetchone()

    if total == 0:
        return ("market data", "warn", "ohlcv empty — backfill runs on first start")

    if spy_count < 60:
        return (
            "market data",
            "warn",
            f"insufficient SPY history for regime detection ({spy_count} bars)",
        )

    latest = row.timestamp if row is not None else None
    if latest is None:
        return ("market data", "ok", f"{total} bars; SPY latest unknown")

    try:
        ts = latest if isinstance(latest, datetime) else datetime.fromisoformat(str(latest))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age_days = (datetime.now(UTC) - ts).days
        if age_days > 5:
            return (
                "market data",
                "warn",
                f"{total} bars; SPY latest {ts.date()} ({age_days}d stale)",
            )
        return ("market data", "ok", f"{total} bars; SPY latest {ts.date()}")
    except Exception:
        return ("market data", "ok", f"{total} bars; SPY latest {latest}")


async def _check_indicators() -> tuple[str, str, str]:
    import ta  # noqa: F401

    return ("indicators (ta)", "ok", "installed")


async def _check_regime_deps() -> tuple[str, str, str]:
    import sklearn  # noqa: F401

    return ("regime deps", "ok", "installed")


async def _check_telegram() -> tuple[str, str, str]:
    from app.config import settings

    if settings.telegram_bot_token and settings.telegram_chat_id:
        return ("telegram", "ok", "configured (alerts + /approve flow + brief push)")
    return ("telegram", "warn", "not configured — no mobile alerts")


async def _check_email() -> tuple[str, str, str]:
    from app.config import settings

    if settings.alert_email_smtp_host and settings.alert_email_to:
        return ("email (smtp)", "ok", "configured")
    return (
        "email (smtp)",
        "warn",
        "not configured — no email alerts/EOD report delivery",
    )


async def _check_broker() -> tuple[str, str, str]:
    from app.config import settings

    broker = settings.execution_broker
    if broker == "PAPER":
        return ("broker", "ok", "PAPER (simulated fills)")
    if broker == "ALPACA":
        if settings.alpaca_api_key and settings.alpaca_api_secret:
            return ("broker", "ok", "ALPACA (keys configured)")
        return ("broker", "fail", "ALPACA selected but keys missing")
    return ("broker", "ok", f"{broker}")


async def _check_mode_halt() -> tuple[str, str, str]:
    from app.config import settings
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()
    mode = await kv.get("horizon:system:mode") or settings.system_mode
    halted = await kv.get("horizon:system:halted")
    risk = await kv.hgetall("horizon:risk:latest")
    kill_switch = risk.get("kill_switch_active")

    if halted == "1" or kill_switch == "1":
        return ("mode / halt", "fail", f"mode {mode}; SYSTEM HALTED — run 'risk reset'")
    return ("mode / halt", "ok", f"mode {mode}")


async def _check_agents(orchestrator) -> tuple[str, str, str]:
    if orchestrator is None:
        return ("agents", "warn", "orchestrator not attached")

    slots = list(orchestrator._slots.values())
    dead = []
    for slot in slots:
        task = slot.task
        if task is not None and task.done():
            cancelled = task.cancelled()
            exc = task.exception() if not cancelled else None
            if exc is not None or slot.status in ("CRASHED", "DEAD"):
                dead.append(slot.agent.agent_id)

    if not dead:
        return ("agents", "ok", f"{len(slots)} agents running")
    return ("agents", "fail", f"dead: {', '.join(dead)}")


async def _check_regime_state() -> tuple[str, str, str]:
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()
    regime = await kv.get("horizon:regime:current")
    if regime:
        return ("regime state", "ok", regime)
    return ("regime state", "warn", "no regime computed yet — run 'brief'")


_CHECKS = [
    ("storage", _check_storage),
    ("bus", _check_bus),
    ("llm keys", _check_llm_keys),
    ("market data", _check_market_data),
    ("indicators (ta)", _check_indicators),
    ("regime deps", _check_regime_deps),
    ("telegram", _check_telegram),
    ("email (smtp)", _check_email),
    ("broker", _check_broker),
    ("mode / halt", _check_mode_halt),
]


async def run_doctor(orchestrator=None) -> str:
    """Run all self-checks and return a Rich-markup report."""
    header = "[bold cyan]═══ SYSTEM DOCTOR ═══[/bold cyan]"
    lines = [header, ""]

    n_ok = n_warn = n_fail = 0

    for name, check in _CHECKS:
        try:
            _, status, detail = await check()
        except Exception as exc:
            status, detail = "fail", str(exc)[:80]
        if status == "ok":
            n_ok += 1
        elif status == "warn":
            n_warn += 1
        else:
            n_fail += 1
        lines.append(_render(name, status, detail))

    try:
        _, status, detail = await _check_agents(orchestrator)
    except Exception as exc:
        status, detail = "fail", str(exc)[:80]
    if status == "ok":
        n_ok += 1
    elif status == "warn":
        n_warn += 1
    else:
        n_fail += 1
    lines.append(_render("agents", status, detail))

    try:
        _, status, detail = await _check_regime_state()
    except Exception as exc:
        status, detail = "fail", str(exc)[:80]
    if status == "ok":
        n_ok += 1
    elif status == "warn":
        n_warn += 1
    else:
        n_fail += 1
    lines.append(_render("regime state", status, detail))

    if n_fail:
        color = "red"
    elif n_warn:
        color = "yellow"
    else:
        color = "green"
    footer = f"[{color}]{n_ok} ok, {n_warn} warnings, {n_fail} failures[/{color}]"
    lines.append("")
    lines.append(footer)

    return "\n".join(lines)
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 622A487CAD69 - verify with scripts/authorship.py verify
