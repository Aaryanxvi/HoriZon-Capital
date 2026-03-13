"""Back Office department manager -- Support & Finance."""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.department_manager import DepartmentManager
from app.agents.departments import DepartmentType
from app.core.logging import get_logger

logger = get_logger("dept.back_office")


class BackOfficeManager(DepartmentManager):
    """Manages accounting, IT, and quant agents."""

    department_type = DepartmentType.BACK_OFFICE
    department_display = "Back Office (Support & Finance)"

    def _create_agents(self) -> list[BaseAgent]:
        agents: list[BaseAgent] = []

        # Accounting
        try:
            from app.agents.back_office.accounting.accounting_agent import AccountingAgent
            agents.append(AccountingAgent(bus=self.bus))
        except ImportError:
            logger.warning("accounting_agent_not_available")

        # IT / Infrastructure
        try:
            from app.agents.back_office.it.it_agent import ITAgent
            agents.append(ITAgent(bus=self.bus))
        except ImportError:
            logger.warning("it_agent_not_available")

        # Quant
        try:
            from app.agents.back_office.quant.quant_agent import QuantAgent
            agents.append(QuantAgent(bus=self.bus))
        except ImportError:
            logger.warning("quant_agent_not_available")

        return agents
