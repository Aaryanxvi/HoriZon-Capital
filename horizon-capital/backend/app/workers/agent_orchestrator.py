"""AgentOrchestrator -- department-based agent management with health monitoring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.agents.base_agent import BaseAgent
from app.agents.department_manager import DepartmentManager
from app.core.logging import get_logger
from app.core.messaging import AgentMessage

logger = get_logger("worker.agent_orchestrator")

MAX_RETRIES = 3
HEALTH_CHECK_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 60  # seconds without heartbeat = unhealthy


class _AgentSlot:
    """Bookkeeping for one agent inside the orchestrator."""

    __slots__ = ("agent", "task", "retries", "last_heartbeat", "status", "department")

    def __init__(self, agent: BaseAgent, department: str = "") -> None:
        self.agent = agent
        self.task: asyncio.Task | None = None
        self.retries: int = 0
        self.last_heartbeat: datetime = datetime.now(UTC)
        self.status: str = "INIT"
        self.department: str = department


class AgentOrchestrator:
    """Central controller that manages all agents via department managers.

    Responsibilities:
    - Instantiate department managers which create their agents.
    - Launch each agent as an independent ``asyncio.Task``.
    - Monitor heartbeats; restart crashed agents (up to ``MAX_RETRIES``).
    - Supervise background workers; restart them on crash.
    - Expose ``start_all`` / ``stop_all`` for clean lifecycle management.
    """

    def __init__(self, bus=None) -> None:
        if bus is None:
            from app.core.runtime import get_bus
            bus = get_bus()
        self.bus = bus
        self._slots: dict[str, _AgentSlot] = {}
        self._departments: dict[str, DepartmentManager] = {}
        self._monitor_task: asyncio.Task | None = None
        self._worker_supervisor_task: asyncio.Task | None = None
        self._running: bool = False
        self._alert_manager = None
        self._health_monitor_svc = None
        # Supervised workers: name -> (worker_instance, task, restart_count)
        self._supervised_workers: dict[str, tuple[Any, asyncio.Task, int]] = {}

    # ------------------------------------------------------------------
    # Department factory
    # ------------------------------------------------------------------

    def _create_departments(self) -> list[DepartmentManager]:
        """Instantiate all department managers."""
        departments: list[DepartmentManager] = []

        try:
            from app.agents.front_office.manager import FrontOfficeManager
            departments.append(FrontOfficeManager(bus=self.bus))
        except ImportError:
            logger.warning("front_office_manager_not_available")

        try:
            from app.agents.middle_office.manager import MiddleOfficeManager
            departments.append(MiddleOfficeManager(bus=self.bus))
        except ImportError:
            logger.warning("middle_office_manager_not_available")

        try:
            from app.agents.back_office.manager import BackOfficeManager
            departments.append(BackOfficeManager(bus=self.bus))
        except ImportError:
            logger.warning("back_office_manager_not_available")

        try:
            from app.agents.executive.manager import ExecutiveManager
            departments.append(ExecutiveManager(bus=self.bus))
        except ImportError:
            logger.warning("executive_manager_not_available")

        return departments

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Instantiate departments & agents, launch each as an asyncio task."""
        self._running = True
        logger.info("agent_orchestrator.starting")

        # Subscribe to heartbeats so we can track liveness
        await self.bus.subscribe("horizon.system.health", self._on_heartbeat)

        # Create departments and their agents
        dept_managers = self._create_departments()
        for mgr in dept_managers:
            self._departments[mgr.department_type.value] = mgr
            await mgr.start_all()

            for agent in mgr.agents:
                slot = _AgentSlot(agent, department=mgr.department_type.value)
                self._slots[agent.agent_id] = slot
                await self._launch_agent(slot)

        # Wire up Alert Manager
        try:
            from app.services.alert_manager import AlertManager
            self._alert_manager = AlertManager(bus=self.bus)
            await self._alert_manager.start()
        except Exception as exc:
            logger.warning("alert_manager_not_available", error=str(exc))

        # Wire up Health Monitor
        try:
            from app.services.health_monitor import HealthMonitor
            self._health_monitor_svc = HealthMonitor(bus=self.bus)
            await self._health_monitor_svc.start()
        except Exception as exc:
            logger.warning("health_monitor_not_available", error=str(exc))

        # Start the health-monitor loop
        self._monitor_task = asyncio.create_task(self._health_monitor())

        # Start the worker supervisor
        self._worker_supervisor_task = asyncio.create_task(self._supervise_workers())

        agent_ids = list(self._slots.keys())
        dept_names = list(self._departments.keys())
        logger.info(
            "agent_orchestrator.started",
            departments=dept_names,
            agents=agent_ids,
        )

    def register_worker(self, name: str, worker: Any, task: asyncio.Task) -> None:
        """Register a background worker for supervision."""
        self._supervised_workers[name] = (worker, task, 0)
        logger.info("worker_registered_for_supervision", worker=name)

    async def stop_all(self) -> None:
        """Cancel all agent tasks and clean up."""
        logger.info("agent_orchestrator.stopping")
        self._running = False

        # Stop worker supervisor
        if self._worker_supervisor_task and not self._worker_supervisor_task.done():
            self._worker_supervisor_task.cancel()
            try:
                await self._worker_supervisor_task
            except asyncio.CancelledError:
                pass

        # Stop health monitor
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Stop each agent
        for slot in self._slots.values():
            await self._cancel_agent(slot)

        # Stop department managers
        for mgr in self._departments.values():
            await mgr.stop_all()

        # Stop all services
        for svc_name in ("_alert_manager", "_health_monitor_svc"):
            svc = getattr(self, svc_name, None)
            if svc:
                try:
                    await svc.stop()
                except Exception:
                    pass

        logger.info("agent_orchestrator.stopped")

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    async def _launch_agent(self, slot: _AgentSlot) -> None:
        """Launch a single agent in its own task."""
        agent = slot.agent
        logger.info("launching_agent", agent_id=agent.agent_id, department=slot.department)
        slot.task = asyncio.create_task(
            self._run_agent(slot),
            name=f"agent-{agent.agent_id}",
        )
        slot.status = "RUNNING"

    async def _run_agent(self, slot: _AgentSlot) -> None:
        """Wrapper that calls ``agent.start()`` and catches crashes."""
        try:
            await slot.agent.start()
        except asyncio.CancelledError:
            slot.status = "STOPPED"
        except Exception as exc:
            slot.status = "CRASHED"
            logger.error(
                "agent_crashed",
                agent_id=slot.agent.agent_id,
                error=str(exc),
                retries=slot.retries,
            )

    async def _cancel_agent(self, slot: _AgentSlot) -> None:
        """Cancel an agent's task and wait for it to finish."""
        if slot.task and not slot.task.done():
            slot.task.cancel()
            try:
                await slot.task
            except asyncio.CancelledError:
                pass
        slot.status = "STOPPED"

    async def _restart_agent(self, slot: _AgentSlot) -> None:
        """Restart a crashed agent if retries remain."""
        if slot.retries >= MAX_RETRIES:
            logger.error(
                "agent_max_retries_exceeded",
                agent_id=slot.agent.agent_id,
                retries=slot.retries,
            )
            slot.status = "DEAD"
            return

        slot.retries += 1
        logger.warning(
            "restarting_agent",
            agent_id=slot.agent.agent_id,
            attempt=slot.retries,
            max_retries=MAX_RETRIES,
        )

        # Cancel any lingering task
        await self._cancel_agent(slot)

        # Brief back-off
        await asyncio.sleep(2 ** slot.retries)

        # Re-launch
        slot.agent._running = False  # reset internal flag
        await self._launch_agent(slot)

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def _on_heartbeat(self, message: AgentMessage) -> None:
        """Track heartbeats from agents."""
        agent_id = message.payload.get("agent_id", "")
        if agent_id in self._slots:
            self._slots[agent_id].last_heartbeat = datetime.now(UTC)

    async def _health_monitor(self) -> None:
        """Periodically check agent health and restart unhealthy ones."""
        try:
            while self._running:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

                now = datetime.now(UTC)
                for agent_id, slot in list(self._slots.items()):
                    # Check if task has crashed
                    if slot.task and slot.task.done() and slot.status != "STOPPED":
                        exc = slot.task.exception() if not slot.task.cancelled() else None
                        if exc is not None:
                            logger.warning(
                                "agent_task_exited_with_error",
                                agent_id=agent_id,
                                error=str(exc),
                            )
                        slot.status = "CRASHED"
                        await self._restart_agent(slot)
                        continue

                    # Check heartbeat freshness
                    elapsed = (now - slot.last_heartbeat).total_seconds()
                    if elapsed > HEARTBEAT_TIMEOUT and slot.status == "RUNNING":
                        logger.warning(
                            "agent_heartbeat_timeout",
                            agent_id=agent_id,
                            elapsed_seconds=elapsed,
                        )
                        slot.status = "UNRESPONSIVE"
                        await self._restart_agent(slot)

        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_agent_statuses(self) -> dict[str, dict[str, Any]]:
        """Return the current status of every managed agent."""
        result: dict[str, dict[str, Any]] = {}
        for agent_id, slot in self._slots.items():
            result[agent_id] = {
                "status": slot.status,
                "retries": slot.retries,
                "last_heartbeat": slot.last_heartbeat.isoformat(),
                "task_done": slot.task.done() if slot.task else True,
                "department": slot.department,
            }
        return result

    def get_department_statuses(self) -> list[dict[str, Any]]:
        """Return status summary for each department."""
        result: list[dict[str, Any]] = []
        for mgr in self._departments.values():
            dept_status = mgr.get_department_status()
            # Enrich with slot-level info
            dept_agents = {
                aid: s for aid, s in self._slots.items()
                if s.department == mgr.department_type.value
            }
            running = sum(1 for s in dept_agents.values() if s.status == "RUNNING")
            dept_status["agents_running"] = running
            dept_status["agents_total"] = len(dept_agents)
            result.append(dept_status)
        return result

    def get_agents_by_department(self) -> dict[str, list[dict[str, Any]]]:
        """Return agents grouped by department."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for agent_id, slot in self._slots.items():
            dept = slot.department or "unassigned"
            if dept not in grouped:
                grouped[dept] = []
            grouped[dept].append({
                "agent_id": agent_id,
                "status": slot.status,
                "retries": slot.retries,
                "last_heartbeat": slot.last_heartbeat.isoformat(),
            })
        return grouped

    def get_worker_statuses(self) -> dict[str, dict[str, Any]]:
        """Return status of all supervised workers."""
        result: dict[str, dict[str, Any]] = {}
        for name, (worker, task, restarts) in self._supervised_workers.items():
            if task.done():
                exc = task.exception() if not task.cancelled() else None
                status = "CRASHED" if exc else "STOPPED"
            elif task.cancelled():
                status = "CANCELLED"
            else:
                status = "RUNNING"
            result[name] = {
                "status": status,
                "restarts": restarts,
                "task_done": task.done(),
            }
        return result

    # ------------------------------------------------------------------
    # Worker supervision
    # ------------------------------------------------------------------

    async def _supervise_workers(self) -> None:
        """Periodically check background workers and restart crashed ones."""
        max_worker_restarts = 5
        try:
            while self._running:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

                for name in list(self._supervised_workers.keys()):
                    worker, task, restarts = self._supervised_workers[name]

                    if not task.done():
                        continue  # Still running

                    exc = task.exception() if not task.cancelled() else None
                    if exc is not None:
                        logger.error(
                            "supervised_worker_crashed",
                            worker=name,
                            error=str(exc),
                            restarts=restarts,
                        )

                    if restarts >= max_worker_restarts:
                        logger.error(
                            "supervised_worker_max_restarts",
                            worker=name,
                            restarts=restarts,
                        )
                        continue

                    # Restart with backoff
                    delay = min(2 ** (restarts + 1), 60)
                    logger.warning(
                        "restarting_worker",
                        worker=name,
                        attempt=restarts + 1,
                        delay=delay,
                    )
                    await asyncio.sleep(delay)

                    new_task = asyncio.create_task(
                        worker.run(), name=name,
                    )
                    self._supervised_workers[name] = (worker, new_task, restarts + 1)

        except asyncio.CancelledError:
            pass
