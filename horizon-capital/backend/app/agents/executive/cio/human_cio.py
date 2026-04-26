"""Human CIO interface -- provides context and data for human decision-making.

This is NOT an agent. It's a helper class used by the CIO chat interface
to gather system state and format it for human consumption.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger("cio.human")


class HumanCIO:
    """Provides data aggregation for the human CIO chat interface.

    Methods here gather and format system state so the CIO chat can
    present it in response to natural language queries.
    """

    def __init__(self, orchestrator=None) -> None:
        self._orchestrator = orchestrator

    def get_system_summary(self) -> dict[str, Any]:
        """Aggregate a high-level system summary for the human CIO."""
        from app.config import settings

        summary: dict[str, Any] = {
            "system_mode": settings.system_mode.value,
            "cio_mode": settings.cio_mode.value,
            "storage_backend": settings.storage_backend.value,
        }

        if self._orchestrator:
            summary["departments"] = self._orchestrator.get_department_statuses()
            summary["agent_count"] = len(self._orchestrator.get_agent_statuses())

        return summary

    def get_department_overview(self) -> list[dict[str, Any]]:
        """Return status of each department."""
        if not self._orchestrator:
            return []
        return self._orchestrator.get_department_statuses()

    def get_pending_approvals(self) -> list[dict[str, Any]]:
        """Return list of items awaiting CIO approval."""
        return []
