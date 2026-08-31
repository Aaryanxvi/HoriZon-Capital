"""Feed a TerminalDashboard from the message bus and the database.

Extracted from ``app.__main__`` so the desktop app can attach the same state to
its own dashboard instance. Several REPL commands (``portfolio``, ``signals``,
``risk``) read dashboard state, so without this the desktop terminal would
answer differently from the CLI one.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger(__name__)


async def route_message(dashboard, orchestrator, msg: AgentMessage) -> None:
    """Apply one bus message to the dashboard's state."""
    if msg.message_type == MessageType.HEARTBEAT:
        payload = msg.payload.copy()
        agent_id = payload.get("agent_id", msg.sender_id)
        if orchestrator is not None:
            statuses = orchestrator.get_agent_statuses()
            if agent_id in statuses:
                payload["department"] = statuses[agent_id].get("department", "")
        dashboard.update_agent_status(agent_id, payload)
    elif msg.message_type == MessageType.AGENT_STATUS:
        agent_id = msg.payload.get("agent_id", msg.sender_id)
        dashboard.update_agent_status(agent_id, msg.payload)
    elif msg.message_type == MessageType.SIGNAL:
        dashboard.add_signal(msg.payload)
    elif msg.message_type == MessageType.RISK_ALERT:
        risk_data = msg.payload.copy()
        try:
            from app.core.kv_store import get_kv_store

            kv = get_kv_store()
            perf = await kv.hgetall("horizon:performance:30d")
            if perf:
                risk_data["sharpe_30d"] = float(perf.get("sharpe_ratio", 0.0))
        except Exception:
            pass
        dashboard.update_risk(risk_data)
    elif msg.message_type == MessageType.PORTFOLIO_UPDATE:
        dashboard.update_portfolio(msg.payload)
    elif msg.message_type == MessageType.TICK:
        dashboard.update_watchlist(msg.payload)
    elif msg.message_type == MessageType.ORDER_NEW:
        # Show every outstanding order (not just human-approval ones).
        # `complete_order` removes it from the pending list when the
        # ORDER_FILL arrives; for paper fills that's milliseconds later,
        # so the user still sees "in flight" on the dashboard.
        if msg.payload.get("order_id"):
            dashboard.add_pending_order(msg.payload)
    elif msg.message_type == MessageType.ORDER_FILL:
        dashboard.complete_order(msg.payload)
    elif msg.message_type == MessageType.ORDER_CANCEL:
        dashboard.remove_order(msg.payload.get("order_id", ""))
    elif msg.message_type == MessageType.SENTIMENT_UPDATE:
        dashboard.update_sentiment(msg.payload)
    elif msg.message_type == MessageType.CIO_ADVISORY:
        dashboard.update_cio_advisory(msg.payload)
    elif msg.message_type == MessageType.HEALTH_CHECK:
        if msg.channel == "horizon.alerts.console":
            dashboard.add_alert(msg.payload)


async def load_initial_state(dashboard) -> None:
    """Seed the dashboard from DB/KV so it is not empty before the first event."""
    try:
        from sqlalchemy import text as sa_text

        from app.core.kv_store import get_kv_store
        from app.core.runtime import get_session_factory

        kv = get_kv_store()

        # Cash & NAV — always publish, even if 0, so the dashboard shows
        # the seeded balance immediately instead of waiting 60s for the
        # first portfolio snapshot.
        cash_usd = float(await kv.get("horizon:cash:usd") or 0)
        cash_inr = float(await kv.get("horizon:cash:inr") or 0)
        nav = float(await kv.get("horizon:portfolio:nav") or 0)
        # Use the best estimate available: persisted NAV, else seeded cash.
        total = nav if nav > 0 else (cash_usd + cash_inr / 83.0)
        dashboard.update_portfolio({
            "total_value": total,
            "cash_usd": cash_usd,
            "cash_inr": cash_inr,
            "positions": [],
        })

        risk = await kv.hgetall("horizon:risk:latest")
        if risk:
            perf = await kv.hgetall("horizon:performance:30d")
            dashboard.update_risk({
                "var_95": float(risk.get("var_1d_95", 0)),
                "var_99": float(risk.get("var_1d_99", 0)),
                "max_drawdown": float(risk.get("max_drawdown", 0)) * 100,
                "current_drawdown": float(risk.get("current_drawdown", 0)) * 100,
                "kill_switch_active": risk.get("kill_switch_active") == "1",
                "sharpe_30d": float(perf.get("sharpe_ratio", 0)) if perf else 0.0,
            })

        async with get_session_factory()() as session:
            result = await session.execute(sa_text("""
                SELECT symbol, exchange, side, quantity,
                       avg_entry_price, current_price,
                       unrealized_pnl, currency
                FROM positions WHERE quantity != 0
            """))
            pos_rows = result.fetchall()
            if pos_rows:
                dashboard._portfolio["positions"] = [
                    {
                        "symbol": r.symbol,
                        "exchange": r.exchange,
                        "side": r.side,
                        "qty": r.quantity,
                        "current_price": r.current_price,
                        "unrealized_pnl": r.unrealized_pnl,
                        "currency": r.currency,
                    }
                    for r in pos_rows
                ]

            result = await session.execute(sa_text("""
                SELECT f.order_id, o.symbol, o.side,
                       f.filled_qty, f.fill_price,
                       f.slippage, f.created_at
                FROM fills f
                JOIN orders o ON f.order_id = o.id
                ORDER BY f.created_at DESC
                LIMIT 20
            """))
            for r in result.fetchall():
                dashboard._trade_history.append({
                    "order_id": r.order_id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "filled_qty": r.filled_qty,
                    "fill_price": r.fill_price,
                    "slippage": r.slippage,
                    "status": "FILLED",
                    "timestamp": str(r.created_at),
                })
    except Exception as exc:
        logger.warning("initial_dashboard_load_error", error=str(exc))


async def attach(dashboard, orchestrator, bus) -> None:
    """Subscribe the dashboard to the bus and seed it with current state."""

    async def _on_any_message(msg: AgentMessage) -> None:
        await route_message(dashboard, orchestrator, msg)

    await bus.subscribe("horizon.*", _on_any_message)
    await load_initial_state(dashboard)
