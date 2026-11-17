"""Desktop org-chart API — the firm's agents and the bus links between them.

Mounted at ``/api/desktop/org``. Static: answers the same with the engine off,
so the Agents page can draw the org before anything runs. Live status comes
from ``/api/desktop/agents``; live traffic from ``ws/live``.

``AGENTS`` mirrors each agent's ``_subscribe()`` / ``emit(channel=...)``;
``tests/test_desktop_org.py`` re-reads the agent sources and fails on drift.
Links are derived, never hand-drawn: A -> B whenever a channel A emits matches
a glob B subscribes to (fnmatch, the same matching MemoryBus uses).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from fastapi import APIRouter

from app.config import CIOMode, settings

router = APIRouter(prefix="/api/desktop/org", tags=["desktop"])

DEPARTMENTS = [
    {"id": "executive", "label": "Executive"},
    {"id": "front_office", "label": "Front office"},
    {"id": "middle_office", "label": "Middle office"},
    {"id": "back_office", "label": "Back office"},
]

# Order within a department is the left-to-right order on the chart (Accounting
# sits right so the Portfolio -> Accounting link clears the middle-office row).
# Per-symbol channels (f"horizon.signal.{symbol}") are written with "*".
AGENTS: list[dict[str, Any]] = [
    {
        "id": "cio-agent-1", "label": "CIO", "department": "executive",
        "module": "app.agents.executive.cio.cio_agent",
        "role": "Advisory every 15 min; crisis mode and override authority over execution",
        "subscribes": ["horizon.risk.*"],
        "emits": ["horizon.executive.cio"],
    },
    {
        "id": "strategy-agent-1", "label": "Strategy", "department": "front_office",
        "module": "app.agents.front_office.strategy.strategy_agent",
        "role": "Runs the strategy sleeves; emits a signal when target weights drift",
        "subscribes": ["horizon.features.*"],
        "emits": ["horizon.tick.*", "horizon.signal.*"],
    },
    {
        "id": "portfolio-agent", "label": "Portfolio", "department": "front_office",
        "module": "app.agents.front_office.portfolio.portfolio_agent",
        "role": "Sizes approved signals, holds the debate gate, owns NAV",
        "subscribes": [
            "horizon.risk.approved.*", "horizon.signal.*", "horizon.debate.*",
            "horizon.execution.order.fill", "horizon.execution.order.update",
        ],
        "emits": [
            "horizon.execution.order.pending", "horizon.execution.order.new",
            "horizon.portfolio.update",
        ],
    },
    {
        "id": "execution-agent", "label": "Execution", "department": "front_office",
        "module": "app.agents.front_office.trading.execution_agent",
        "role": "Kill-switch, cash and short guards; routes orders to the broker",
        "subscribes": [
            "horizon.execution.order.new", "horizon.execution.order.pending",
            "horizon.execution.order.cancel", "horizon.executive.cio",
        ],
        "emits": [
            "horizon.risk.alert", "horizon.execution.order.tracked",
            "horizon.execution.order.update", "horizon.execution.order.fill",
        ],
    },
    {
        "id": "ir-agent-1", "label": "Investor relations", "department": "front_office",
        "module": "app.agents.front_office.investor_relations.ir_agent",
        "role": "Hourly investor reports from portfolio and risk updates",
        "subscribes": ["horizon.portfolio.*", "horizon.risk.*"],
        "emits": ["horizon.ir.report"],
    },
    {
        "id": "risk-agent", "label": "Risk", "department": "middle_office",
        "module": "app.agents.middle_office.risk.risk_agent",
        "role": "Pre-trade limit gate, VaR/CVaR/drawdown every 30s, kill switch",
        "subscribes": ["horizon.signal.*", "horizon.execution.order.*"],
        "emits": [
            "horizon.risk.approved.*", "horizon.risk.alert", "horizon.risk.rejected.*",
            "horizon.risk.metrics",
        ],
    },
    {
        "id": "debate-agent-1", "label": "Debate", "department": "middle_office",
        "module": "app.agents.middle_office.debate_agent",
        "role": "Multi-model LLM debate on risk-approved trades",
        "subscribes": ["horizon.risk.approved.*"],
        "emits": ["horizon.debate.*"],
    },
    {
        "id": "compliance-agent-1", "label": "Compliance", "department": "middle_office",
        "module": "app.agents.middle_office.compliance.compliance_agent",
        "role": "Restricted symbols and concentration checks",
        "subscribes": ["horizon.signal.*", "horizon.execution.order.*"],
        "emits": ["horizon.compliance.alert"],
    },
    {
        "id": "alpha-monitor-1", "label": "Alpha monitor", "department": "middle_office",
        "module": "app.agents.middle_office.alpha_monitor",
        "role": "Rolling Sharpe and win-rate; alerts on alpha decay",
        "subscribes": ["horizon.execution.*", "horizon.signal.*"],
        "emits": ["horizon.alpha.decay", "horizon.alpha.snapshot"],
    },
    {
        "id": "operations-agent-1", "label": "Operations", "department": "middle_office",
        "module": "app.agents.middle_office.operations.operations_agent",
        "role": "Detects stuck orders",
        "subscribes": ["horizon.execution.order.*"],
        "emits": ["horizon.operations.alert"],
    },
    {
        "id": "quant-agent-1", "label": "Quant", "department": "back_office",
        "module": "app.agents.back_office.quant.quant_agent",
        "role": "Feature freshness checks",
        "subscribes": ["horizon.features.*"],
        "emits": [],
    },
    {
        "id": "it-agent-1", "label": "IT", "department": "back_office",
        "module": "app.agents.back_office.it.it_agent",
        "role": "Host health (CPU, memory, disk) via psutil",
        "subscribes": [],
        "emits": ["horizon.it.alert", "horizon.it.status"],
    },
    {
        "id": "accounting-agent-1", "label": "Accounting", "department": "back_office",
        "module": "app.agents.back_office.accounting.accounting_agent",
        "role": "NAV and P&L snapshots from portfolio updates",
        "subscribes": ["horizon.portfolio.*"],
        "emits": ["horizon.accounting.snapshot"],
    },
]


def build_links() -> list[dict[str, Any]]:
    links = []
    for src in AGENTS:
        for dst in AGENTS:
            if src is dst:
                continue
            channels = [
                c for c in src["emits"] if any(fnmatchcase(c, s) for s in dst["subscribes"])
            ]
            if channels:
                links.append({"from": src["id"], "to": dst["id"], "channels": channels})
    return links


@router.get("")
async def org() -> dict[str, Any]:
    # ExecutiveManager only starts the CIO agent in AI mode.
    cio_off = settings.cio_mode != CIOMode.AI
    agents = []
    for a in AGENTS:
        off = cio_off and a["id"] == "cio-agent-1"
        agents.append({
            **{k: v for k, v in a.items() if k != "module"},
            "enabled": not off,
            "note": "Human CIO mode: the CIO agent does not run" if off else None,
        })
    return {"departments": DEPARTMENTS, "agents": agents, "links": build_links()}
