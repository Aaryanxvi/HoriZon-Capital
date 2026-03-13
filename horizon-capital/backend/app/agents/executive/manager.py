"""Executive department manager -- Executive Management."""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.department_manager import DepartmentManager
from app.agents.departments import DepartmentType
from app.config import CIOMode, settings
from app.core.logging import get_logger

logger = get_logger("dept.executive")


class ExecutiveManager(DepartmentManager):
    """Manages the CIO agent (AI mode only -- human CIO uses chat interface)."""

    department_type = DepartmentType.EXECUTIVE
    department_display = "Executive (Management)"

    def _create_agents(self) -> list[BaseAgent]:
        agents: list[BaseAgent] = []

        if settings.cio_mode == CIOMode.AI:
            try:
                from app.agents.executive.cio.cio_agent import CIOAgent
                agents.append(CIOAgent(bus=self.bus))
            except ImportError:
                logger.warning("cio_agent_not_available")
        else:
            logger.info("cio_human_mode_active")

        return agents
