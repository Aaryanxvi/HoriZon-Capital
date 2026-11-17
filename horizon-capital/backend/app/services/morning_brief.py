# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-BC673B4055AE
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Morning briefing: overnight P&L, regime, risk, pending orders, stops, debates.

Each section is built as structured data — ``{"title", "lines"}`` where a line is
a list of ``(text, tone)`` segments and ``tone`` is a Rich colour name or None.
``build_morning_brief`` renders that to Rich markup for the REPL / push worker;
``build_morning_brief_sections`` hands the same data to the desktop UI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

HEADER_COLOR = "bold cyan"

Segment = tuple[str, str | None]
Section = dict[str, Any]

# detect_regime needs lookback (252) + 25 closes; below that it returns a
# meaningless ("RISK_OFF", 0.0).
_REGIME_MIN_CLOSES = 277


def _get_session_factory():
    from app.core.runtime import get_session_factory

    return get_session_factory()


def _section(title: str, *lines: list[Segment]) -> Section:
    return {"title": title, "lines": list(lines)}


def _unavailable(title: str, why: str = "unavailable") -> Section:
    return _section(title, [(why, "dim")])


def _render(section: Section) -> str:
    out = [f"[{HEADER_COLOR}]{section['title']}[/{HEADER_COLOR}]"]
    for line in section["lines"]:
        out.append("  " + "".join(f"[{tone}]{t}[/{tone}]" if tone else t for t, tone in line))
    return "\n".join(out)


async def compute_spy_regime() -> dict[str, Any] | None:
    """Fit the GMM regime on stored SPY daily closes; None if history is too short.

    Same model as ResearchStackSleeve. ``p_risk_on`` is the posterior of the
    risk-on cluster (the sleeve's ``conf``); ``state`` is RISK_ON when > 0.5.
    """
    import pandas as pd

    from app.quant.regime_hmm import detect_regime

    async with _get_session_factory()() as session:
        result = await session.execute(
            text(
                "SELECT close, timestamp FROM ohlcv WHERE timeframe = '1d' "
                "AND (symbol = 'SPY' OR symbol LIKE 'SPY.%') AND close IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 300"
            )
        )
        rows = result.fetchall()[::-1]

    if len(rows) < _REGIME_MIN_CLOSES:
        return None
    state, p_on = detect_regime(pd.Series([r.close for r in rows]))
    return {"state": state, "p_risk_on": p_on, "as_of": str(rows[-1].timestamp)}


async def _section_pnl() -> Section:
    title = "Overnight P&L"
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

        lines: list[list[Segment]] = []
        if row is not None and row.total_value and row.total_value > 0:
            ref_nav = float(row.total_value)
            delta = nav - ref_nav
            pct = delta / ref_nav * 100
            color = "green" if delta >= 0 else "red"
            lines.append([
                (f"NAV ${nav:,.2f} (", None),
                (f"Δ ${delta:+,.2f} / {pct:+.2f}% overnight", color),
                (")", None),
            ])
        else:
            lines.append([(f"NAV ${nav:,.2f}", None)])
            lines.append([("no prior snapshot for comparison", "dim")])
        lines.append([(f"Cash: ${cash:,.2f}", None)])
        return _section(title, *lines)
    except Exception:
        return _unavailable(title)


async def _section_regime() -> Section:
    title = "Regime"
    insufficient = "unavailable (insufficient SPY history)"
    try:
        regime = await compute_spy_regime()
        if regime is None:
            return _unavailable(title, insufficient)
        state, conf = regime["state"], regime["p_risk_on"]
        color = "green" if state == "RISK_ON" else "yellow"

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

        return _section(title, [(state, color), (f" (confidence {conf * 100:.0f}%)", None)])
    except Exception:
        return _unavailable(title, insufficient)


async def _section_risk() -> Section:
    title = "Risk Snapshot"
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        risk = await kv.hgetall("horizon:risk:latest")
        halted = await kv.get("horizon:system:halted")

        var_95 = float(risk.get("var_1d_95", 0.0) or 0.0) * 100
        curr_dd = float(risk.get("current_drawdown", 0.0) or 0.0) * 100
        kill_active = risk.get("kill_switch_active") == "1"
        kill: Segment = ("ACTIVE", "red") if kill_active else ("clear", "green")

        lines: list[list[Segment]] = [
            [(f"VaR (95%):        {var_95:.2f}%", None)],
            [(f"Current Drawdown: {curr_dd:.2f}%", None)],
            [("Kill switch:      ", None), kill],
        ]
        if halted == "1":
            lines.append([("⚠ SYSTEM HALTED — run 'risk reset' to clear", "red")])
        return _section(title, *lines)
    except Exception:
        return _unavailable(title)


async def _section_pending(orchestrator) -> Section:
    title = "Pending Approvals"
    try:
        from app.core.kv_store import get_kv_store

        kv = get_kv_store()
        mode = await kv.get("horizon:system:mode") or "unknown"

        lines: list[list[Segment]] = [[(f"Trading mode: {mode}", None)]]

        agent = None
        if orchestrator is not None:
            for slot in orchestrator._slots.values():
                if slot.agent.agent_type == "execution":
                    agent = slot.agent
                    break

        if agent is None:
            lines.append([("execution agent not available", "dim")])
            return _section(title, *lines)

        pending = agent.get_pending_approvals()
        if not pending:
            lines.append([("none", "green")])
        else:
            for o in pending:
                oid = str(o.get("id", ""))[:8]
                lines.append([(f"{oid}  {o['side']} {o['quantity']} {o['symbol']}", None)])
        return _section(title, *lines)
    except Exception:
        return _unavailable(title)


async def _section_stops() -> Section:
    title = "Positions Near Stop"
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

        no_positions = [("no open positions", "dim")]
        if not rows:
            return _section(title, no_positions)

        lines: list[list[Segment]] = []
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
            msg = (
                f"{r.symbol}: price {price:.2f}, "
                f"stop {r.stop_loss_price:.2f}, {distance_pct:.1f}% away"
            )
            if distance_pct <= 5.0:
                lines.append([(f"⚠ {msg}", "yellow")])
            else:
                lines.append([(msg, None)])

        if not any_row:
            lines.append(no_positions)

        return _section(title, *lines)
    except Exception:
        return _unavailable(title)


async def _section_debates() -> Section:
    title = "Debates (last 24h)"
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

        if not rows:
            return _section(title, [("no debates in the last 24h", "dim")])

        lines: list[list[Segment]] = []
        for r in rows:
            decision = r.final_decision or "--"
            color = (
                "green" if decision == "APPROVED"
                else "red" if decision == "REJECTED"
                else "dim"
            )
            score = float(r.consensus_score) if r.consensus_score is not None else 0.0
            lines.append([
                (f"{r.symbol} {r.proposed_action or ''} — ", None),
                (decision, color),
                (f" ({score:.2f}) {r.reason or ''}", None),
            ])
        return _section(title, *lines)
    except Exception:
        return _unavailable(title)


async def build_morning_brief_sections(orchestrator=None) -> list[Section]:
    """The briefing as structured sections (see module docstring)."""
    return [
        await _section_pnl(),
        await _section_regime(),
        await _section_risk(),
        await _section_pending(orchestrator),
        await _section_stops(),
        await _section_debates(),
    ]


async def build_morning_brief(orchestrator=None) -> str:
    """Build the morning briefing as a single Rich-markup string."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    header = f"[bold cyan]═══ MORNING BRIEF — {today} ═══[/bold cyan]"
    sections = await build_morning_brief_sections(orchestrator)
    return "\n\n".join([header, *(_render(s) for s in sections)])
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token BC673B4055AE - verify with scripts/authorship.py verify
