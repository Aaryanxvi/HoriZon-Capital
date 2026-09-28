# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-C26C7EDC7559
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Base class for department managers.

Department managers are structural containers (NOT agents) that create,
start, stop, and report on all agents within their department.
"""

from __future__ import annotations

import abc
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.departments import DepartmentType
from app.core.logging import get_logger


class DepartmentManager(abc.ABC):
    """Base class for all department managers.

    A department manager owns a group of agents and provides lifecycle
    management.  It is NOT a BaseAgent -- it's a structural container.
    """

    department_type: DepartmentType
    department_display: str = ""

    def __init__(self, bus) -> None:
        self.bus = bus
        self.agents: list[BaseAgent] = []
        self.logger = get_logger(f"dept.{self.department_type.value}")

    @abc.abstractmethod
    def _create_agents(self) -> list[BaseAgent]:
        """Instantiate all agents for this department."""
        ...

    async def start_all(self) -> None:
        """Create and start all agents in this department."""
        self.agents = self._create_agents()
        self.logger.info(
            "department_starting",
            department=self.department_display,
            agent_count=len(self.agents),
        )

    async def stop_all(self) -> None:
        """Stop all agents in this department."""
        for agent in self.agents:
            try:
                await agent.stop()
            except Exception as exc:
                self.logger.error(
                    "agent_stop_error",
                    agent_id=agent.agent_id,
                    error=str(exc),
                )
        self.logger.info("department_stopped", department=self.department_display)

    def get_agent_statuses(self) -> dict[str, dict[str, Any]]:
        """Return status info for all agents in this department."""
        result: dict[str, dict[str, Any]] = {}
        for agent in self.agents:
            result[agent.agent_id] = {
                "agent_type": agent.agent_type,
                "department": self.department_type.value,
                "status": "RUNNING" if agent._running else "STOPPED",
            }
        return result

    def get_department_status(self) -> dict[str, Any]:
        """Return a summary of the department's health."""
        agent_statuses = self.get_agent_statuses()
        running = sum(1 for s in agent_statuses.values() if s["status"] == "RUNNING")
        total = len(agent_statuses)
        return {
            "department": self.department_type.value,
            "display_name": self.department_display,
            "agents_total": total,
            "agents_running": running,
            "agents_stopped": total - running,
            "healthy": running == total,
        }
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token C26C7EDC7559 - verify with scripts/authorship.py verify
