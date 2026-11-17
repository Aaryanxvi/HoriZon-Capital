"""Desktop brief API — the morning brief and the market-regime gauge.

Mounted at ``/api/desktop/brief``. Read-only apart from what the morning brief
itself has always done (log the regime it computed to ``regime_states``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from app.api.desktop import _f, _orchestrator, _query
from app.api.desktop_viz import sleeves as _live_sleeves
from app.services.morning_brief import build_morning_brief_sections, compute_spy_regime

router = APIRouter(prefix="/api/desktop/brief", tags=["desktop"])


@router.get("")
async def brief(request: Request) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat(),
        "sections": await build_morning_brief_sections(_orchestrator(request)),
    }


def _configured_mix() -> list[dict[str, Any]]:
    # Engine off: the mix a fresh StrategyAgent would run (respects the optional
    # sleeve settings). Construction is side-effect free — universe loads lazily.
    from app.agents.front_office.strategy.strategy_agent import StrategyAgent

    return [
        {"name": s.name, "weight": _f(s.target_weight), "cadence_days": s.rebalance_days,
         "last_refresh": None, "signals": []}
        for s in StrategyAgent(bus=None)._sleeves
    ]


@router.get("/regime")
async def regime(request: Request) -> dict[str, Any]:
    # ponytail: GMM refit per request (~tens of ms on 300 bars); cache if polled hard.
    try:
        current = await compute_spy_regime()
    except Exception:
        current = None

    # Last regime per UTC day, as logged by the morning brief.
    history = [
        {"date": r["date"], "state": r["regime"], "p_risk_on": _f(r["confidence"])}
        for r in await _query(
            "SELECT date(created_at) AS date, regime, confidence, max(created_at) AS ts "
            "FROM regime_states GROUP BY date(created_at) ORDER BY date DESC LIMIT 60"
        )
    ][::-1]

    source = "computed"
    if current is None and history:
        last = history[-1]
        current = {"state": last["state"], "p_risk_on": last["p_risk_on"], "as_of": last["date"]}
        source = "stored"

    live = await _live_sleeves(request)
    return {
        "available": current is not None,
        "source": source if current is not None else None,
        "state": current and current["state"],
        "p_risk_on": current and _f(current["p_risk_on"]),
        "as_of": current and current["as_of"],
        "history": history,
        "sleeves_live": live["available"],
        "sleeves": live["sleeves"] if live["available"] else _configured_mix(),
    }
