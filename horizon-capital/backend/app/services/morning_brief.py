"""Morning briefing: overnight P&L, regime, risk, pending orders, stops, debates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

HEADER_COLOR = "bold cyan"


def _get_session_factory():
    from app.core.runtime import get_session_factory

    return get_session_factory()


async def _section_pnl() -> str:
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        nav_str = await kv.get("horizon:portfolio:nav")
        cash_str = await kv.get("horizon:cash:usd")
        nav = float(nav_str) if nav_str else 0.0
        cash = float(cash_str) if cash_str else 0.0

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT total_value, created_at FROM portfolio_snapshots "
                    "WHERE substr(created_at,1,10) < :today "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"today": today},
            )
            row = result.fetchone()

        lines = ["[bold cyan]Overnight P&L[/bold cyan]"]
        if row is not None and row.total_value and row.total_value > 0:
            ref_nav = float(row.total_value)
            delta = nav - ref_nav
            pct = delta / ref_nav * 100
            color = "green" if delta >= 0 else "red"
            lines.append(
                f"  NAV ${nav:,.2f} "
                f"([{color}]Δ ${delta:+,.2f} / {pct:+.2f}% overnight[/{color}])"
            )
        else:
            lines.append(f"  NAV ${nav:,.2f}")
            lines.append("  [dim]no prior snapshot for comparison[/dim]")
        lines.append(f"  Cash: ${cash:,.2f}")
        return "\n".join(lines)
    except Exception:
        return "[bold cyan]Overnight P&L[/bold cyan]\n  [dim]unavailable[/dim]"


async def _section_regime() -> str:
    try:
        import pandas as pd

        from app.quant.regime_hmm import detect_regime

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT close FROM ohlcv WHERE symbol = 'SPY' "
                    "ORDER BY timestamp ASC"
                )
            )
            rows = result.fetchall()
            if not rows:
                result = await session.execute(
                    text(
                        "SELECT close FROM ohlcv WHERE symbol LIKE 'SPY%' "
                        "ORDER BY timestamp ASC"
                    )
                )
                rows = result.fetchall()

        closes = [r.close for r in rows if r.close is not None]
        closes = closes[-300:]

        if len(closes) < 60:
            return (
                "[bold cyan]Regime[/bold cyan]\n"
                "  [dim]unavailable (insufficient SPY history)[/dim]"
            )

        state, conf = detect_regime(pd.Series(closes))
        color = "green" if state == "RISK_ON" else "yellow"
        result_line = f"  [{color}]{state}[/{color}] (confidence {conf * 100:.0f}%)"

        try:
            from app.core.kv_store import get_kv_store

            kv = get_kv_store()
            async with _get_session_factory()() as session:
                await session.execute(
                    text(
                        "INSERT INTO regime_states "
                        "(id, regime, confidence, method, market_scope, created_at) "
                        "VALUES (:id, :regime, :confidence, :method, :scope, :created_at)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "regime": state,
                        "confidence": conf,
                        "method": "gmm",
                        "scope": "US",
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
                await session.commit()
            await kv.set("horizon:regime:current", state)
        except Exception:
            pass

        return "[bold cyan]Regime[/bold cyan]\n" + result_line
    except Exception:
        return (
            "[bold cyan]Regime[/bold cyan]\n"
            "  [dim]unavailable (insufficient SPY history)[/dim]"
        )


async def _section_risk() -> str:
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        risk = await kv.hgetall("horizon:risk:latest")
        halted = await kv.get("horizon:system:halted")

        var_95 = float(risk.get("var_1d_95", 0.0) or 0.0) * 100
        curr_dd = float(risk.get("current_drawdown", 0.0) or 0.0) * 100
        kill_active = risk.get("kill_switch_active") == "1"
        kill_str = (
            "[red]ACTIVE[/red]" if kill_active else "[green]clear[/green]"
        )

        lines = [
            "[bold cyan]Risk Snapshot[/bold cyan]",
            f"  VaR (95%):        {var_95:.2f}%",
            f"  Current Drawdown: {curr_dd:.2f}%",
            f"  Kill switch:      {kill_str}",
        ]
        if halted == "1":
            lines.append(
                "  [red]⚠ SYSTEM HALTED — run 'risk reset' to clear[/red]"
            )
        return "\n".join(lines)
    except Exception:
        return "[bold cyan]Risk Snapshot[/bold cyan]\n  [dim]unavailable[/dim]"


async def _section_pending(orchestrator) -> str:
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        mode = await kv.get("horizon:system:mode") or "unknown"

        lines = [
            "[bold cyan]Pending Approvals[/bold cyan]",
            f"  Trading mode: {mode}",
        ]

        agent = None
        if orchestrator is not None:
            for slot in orchestrator._slots.values():
                if slot.agent.agent_type == "execution":
                    agent = slot.agent
                    break

        if agent is None:
            lines.append("  [dim]execution agent not available[/dim]")
            return "\n".join(lines)

        pending = agent.get_pending_approvals()
        if not pending:
            lines.append("  [green]none[/green]")
        else:
            for o in pending:
                oid = str(o.get("id", ""))[:8]
                lines.append(
                    f"  {oid}  {o['side']} {o['quantity']} {o['symbol']}"
                )
        return "\n".join(lines)
    except Exception:
        return "[bold cyan]Pending Approvals[/bold cyan]\n  [dim]unavailable[/dim]"


async def _section_stops() -> str:
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()

        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT symbol, exchange, quantity, avg_entry_price, "
                    "current_price, stop_loss_price, unrealized_pnl "
                    "FROM positions WHERE quantity > 0"
                )
            )
            rows = result.fetchall()

        lines = ["[bold cyan]Positions Near Stop[/bold cyan]"]
        if not rows:
            lines.append("  [dim]no open positions[/dim]")
            return "\n".join(lines)

        any_row = False
        for r in rows:
            if r.stop_loss_price is None or r.stop_loss_price <= 0:
                continue
            any_row = True
            price_str = await kv.get(f"horizon:price:{r.symbol}")
            price = float(price_str) if price_str else float(r.current_price or 0.0)
            if price <= 0:
                continue
            distance_pct = (price - r.stop_loss_price) / price * 100
            if distance_pct <= 5.0:
                lines.append(
                    f"  [yellow]⚠ {r.symbol}: price {price:.2f}, "
                    f"stop {r.stop_loss_price:.2f}, {distance_pct:.1f}% away[/yellow]"
                )
            else:
                lines.append(
                    f"  {r.symbol}: price {price:.2f}, "
                    f"stop {r.stop_loss_price:.2f}, {distance_pct:.1f}% away"
                )

        if not any_row:
            lines.append("  [dim]no open positions[/dim]")

        return "\n".join(lines)
    except Exception:
        return "[bold cyan]Positions Near Stop[/bold cyan]\n  [dim]unavailable[/dim]"


async def _section_debates() -> str:
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        async with _get_session_factory()() as session:
            result = await session.execute(
                text(
                    "SELECT symbol, proposed_action, final_decision, "
                    "consensus_score, reason, created_at FROM debate_sessions "
                    "WHERE created_at >= :cutoff ORDER BY created_at DESC LIMIT 10"
                ),
                {"cutoff": cutoff},
            )
            rows = result.fetchall()

        lines = ["[bold cyan]Debates (last 24h)[/bold cyan]"]
        if not rows:
            lines.append("  [dim]no debates in the last 24h[/dim]")
            return "\n".join(lines)

        for r in rows:
            decision = r.final_decision or "--"
            color = (
                "green" if decision == "APPROVED"
                else "red" if decision == "REJECTED"
                else "dim"
            )
            score = float(r.consensus_score) if r.consensus_score is not None else 0.0
            lines.append(
                f"  {r.symbol} {r.proposed_action or ''} — "
                f"[{color}]{decision}[/{color}] ({score:.2f}) {r.reason or ''}"
            )
        return "\n".join(lines)
    except Exception:
        return "[bold cyan]Debates (last 24h)[/bold cyan]\n  [dim]unavailable[/dim]"


async def build_morning_brief(orchestrator=None) -> str:
    """Build the morning briefing as a single Rich-markup string."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    header = f"[bold cyan]═══ MORNING BRIEF — {today} ═══[/bold cyan]"

    sections = [
        await _section_pnl(),
        await _section_regime(),
        await _section_risk(),
        await _section_pending(orchestrator),
        await _section_stops(),
        await _section_debates(),
    ]

    return "\n\n".join([header, *sections])
