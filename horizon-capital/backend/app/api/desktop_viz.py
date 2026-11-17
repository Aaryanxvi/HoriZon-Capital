# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B27A5513BCC3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Desktop viz API — read-only aggregations the charts need, LOCAL SQLite only.

Mounted at ``/api/desktop/viz``. Same rules as ``api/desktop.py``: raw SQL over
the tables the terminal reads, never a write, never a strategy tick.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request

from app.api.desktop import _f, _orchestrator, _query

router = APIRouter(prefix="/api/desktop/viz", tags=["desktop"])


def _since(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).date().isoformat()


@router.get("/nav-daily")
async def nav_daily(days: int = Query(3650, ge=1, le=20000)) -> dict[str, Any]:
    # SQLite bare columns next to max() come from the row holding the max:
    # one row per UTC day = that day's last snapshot.
    rows = await _query(
        "SELECT date(created_at) AS date, total_value, cash_usd, equity_value, "
        "max(created_at) AS ts FROM portfolio_snapshots "
        "WHERE date(created_at) >= :since GROUP BY date(created_at) ORDER BY date",
        {"since": _since(days)},
    )
    points = [
        {
            "date": r["date"],
            "nav": _f(r["total_value"]),
            "cash_usd": _f(r["cash_usd"]),
            "equity_value": _f(r["equity_value"]),
        }
        for r in rows
    ]
    return {"points": points, "days_recorded": len(points)}


@router.get("/benchmark")
async def benchmark(
    symbol: str = Query("SPY", pattern=r"^[A-Za-z0-9.^\-]{1,24}$"),
    days: int = Query(3650, ge=1, le=20000),
) -> dict[str, Any]:
    sym = symbol.upper()
    # Positions carry exchange suffixes (SPY.NYSE); ohlcv may store bare SPY.
    rows = await _query(
        "SELECT date(timestamp) AS date, close, max(timestamp) AS ts FROM ohlcv "
        "WHERE timeframe = '1d' AND (symbol = :sym OR symbol LIKE :sym || '.%') "
        "AND date(timestamp) >= :since GROUP BY date(timestamp) ORDER BY date",
        {"sym": sym, "since": _since(days)},
    )
    return {"symbol": sym, "points": [{"date": r["date"], "close": _f(r["close"])} for r in rows]}


@router.get("/sleeves")
async def sleeves(request: Request) -> dict[str, Any]:
    # Located the way `tui/commands.py::_cmd_strategy` does; read-only, no _tick.
    slots = getattr(_orchestrator(request), "_slots", None) or {}
    agent = next(
        (s.agent for s in slots.values() if s.agent.agent_type == "strategy"), None
    )
    if agent is None:
        return {"available": False, "market_open": None, "sleeves": [], "targets": {}}

    from app.agents.front_office.strategy.strategy_agent import _is_us_market_open

    out = []
    for sleeve in agent._sleeves:
        last = agent._sleeve_last_refresh.get(sleeve.name)
        out.append({
            "name": sleeve.name,
            "weight": _f(sleeve.target_weight),
            "cadence_days": sleeve.rebalance_days,
            "last_refresh": last.isoformat() if last is not None else None,
            "signals": [
                {"symbol": sig.symbol, "weight": _f(sig.target_weight * sleeve.target_weight)}
                for sig in agent._sleeve_cache.get(sleeve.name, [])
            ],
        })
    return {
        "available": True,
        "market_open": _is_us_market_open(),
        "sleeves": out,
        "targets": {s: _f(w) for s, w in agent._last_emitted_weight.items()},
    }
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B27A5513BCC3 - verify with scripts/authorship.py verify
