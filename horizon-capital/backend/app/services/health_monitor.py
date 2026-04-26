"""System Health & Observability Service.

Provides system-wide health monitoring including agent uptime, message
throughput, latency tracking, memory usage, and system diagnostics.
Tracks four key metrics: latency, traffic, errors, and resource saturation.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import text as sa_text

from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger("services.health_monitor")


@dataclass
class AgentHealth:
    """Health status for a single agent."""

    agent_id: str
    status: str = "UNKNOWN"
    uptime_seconds: float = 0.0
    last_heartbeat: str = ""
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    restarts: int = 0
    department: str = ""


@dataclass
class SystemHealthSnapshot:
    """Point-in-time system health snapshot."""

    timestamp: str
    # Agent metrics
    total_agents: int = 0
    agents_running: int = 0
    agents_crashed: int = 0
    agents_unresponsive: int = 0

    # Message bus metrics
    messages_per_minute: float = 0.0
    avg_message_latency_ms: float = 0.0
    bus_queue_depth: int = 0

    # System metrics
    memory_usage_mb: float = 0.0
    cpu_percent: float = 0.0
    uptime_hours: float = 0.0

    # Data pipeline
    last_data_ingestion: str = ""
    data_freshness_seconds: float = 0.0
    ohlcv_symbols_tracked: int = 0

    # Risk
    kill_switch_active: bool = False
    var_breach: bool = False

    # Agent details
    agent_details: list[dict] = field(default_factory=list)


class HealthMonitor:
    """System-wide health monitoring service.

    Tracks four key metrics:
    1. Latency — message processing time
    2. Traffic — message throughput
    3. Errors — agent crashes, message failures
    4. Saturation — queue depth, memory usage

    Subscribes to the message bus to passively monitor system health.
    """

    def __init__(self, bus=None) -> None:
        if bus is None:
            from app.core.runtime import get_bus
            bus = get_bus()
        self.bus = bus
        self._start_time = time.time()
        self._running = False

        # Message tracking (sliding window)
        self._message_timestamps: deque[float] = deque(maxlen=10000)
        self._message_latencies: deque[float] = deque(maxlen=1000)
        self._total_messages: int = 0
        self._total_errors: int = 0

        # Agent tracking
        self._agent_health: dict[str, AgentHealth] = {}
        self._agent_start_times: dict[str, float] = {}

        # Snapshots history
        self._snapshots: list[SystemHealthSnapshot] = []
        self._max_snapshots = 1440  # 24 hours at 1/min

        # Monitor task
        self._monitor_task: asyncio.Task | None = None

        # psutil process handle (kept alive for CPU delta sampling)
        self._process = None
        try:
            import psutil
            self._process = psutil.Process()
            self._process.cpu_percent(interval=0)  # prime the sampler
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start health monitoring."""
        self._running = True
        self._start_time = time.time()

        await self.bus.subscribe("horizon.*", self._on_message)
        self._monitor_task = asyncio.create_task(self._periodic_snapshot())

        logger.info("health_monitor.started")

    async def stop(self) -> None:
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("health_monitor.stopped")

    # ------------------------------------------------------------------
    # Message tracking
    # ------------------------------------------------------------------

    async def _on_message(self, msg: AgentMessage) -> None:
        """Track all messages passing through the bus."""
        now = time.time()
        self._message_timestamps.append(now)
        self._total_messages += 1

        # Latency = wall time between message creation and receipt on bus
        try:
            sent_ts = msg.timestamp.timestamp()
            latency = now - sent_ts
            if 0 <= latency < 60:
                self._message_latencies.append(latency)
        except (AttributeError, TypeError, ValueError):
            pass

        # Track per-agent messages
        sender = msg.sender_id
        if sender not in self._agent_health:
            self._agent_health[sender] = AgentHealth(agent_id=sender)
            self._agent_start_times[sender] = now
        self._agent_health[sender].messages_sent += 1

        # Track heartbeats
        if msg.message_type == MessageType.HEARTBEAT:
            agent_id = msg.payload.get("agent_id", sender)
            if agent_id not in self._agent_health:
                self._agent_health[agent_id] = AgentHealth(agent_id=agent_id)
                self._agent_start_times[agent_id] = now
            ah = self._agent_health[agent_id]
            ah.status = msg.payload.get("status", "RUNNING")
            ah.last_heartbeat = datetime.now(UTC).isoformat()
            ah.department = msg.payload.get("department", ah.department)

    # ------------------------------------------------------------------
    # Periodic snapshot
    # ------------------------------------------------------------------

    async def _periodic_snapshot(self) -> None:
        """Take a health snapshot every 60 seconds."""
        try:
            while self._running:
                await asyncio.sleep(60)
                snapshot = await self.get_snapshot()
                self._snapshots.append(snapshot)
                if len(self._snapshots) > self._max_snapshots:
                    self._snapshots = self._snapshots[-self._max_snapshots:]
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Snapshot computation
    # ------------------------------------------------------------------

    async def get_snapshot(self, orchestrator=None) -> SystemHealthSnapshot:
        """Compute current system health snapshot."""
        now = time.time()
        now_utc = datetime.now(UTC)

        # Message throughput (messages in last 60 seconds)
        cutoff = now - 60
        recent = sum(1 for t in self._message_timestamps if t > cutoff)
        mpm = float(recent)

        # System metrics
        memory_mb = 0.0
        cpu_pct = 0.0
        if self._process is not None:
            try:
                memory_mb = self._process.memory_info().rss / (1024 * 1024)
                cpu_pct = self._process.cpu_percent(interval=0)
            except Exception:
                pass
        else:
            try:
                import psutil
                self._process = psutil.Process()
                self._process.cpu_percent(interval=0)
                memory_mb = self._process.memory_info().rss / (1024 * 1024)
            except Exception:
                pass

        # Agent counts from orchestrator if available
        total_agents = 0
        running = 0
        crashed = 0
        unresponsive = 0
        agent_details = []

        if orchestrator:
            statuses = orchestrator.get_agent_statuses()
            total_agents = len(statuses)
            for aid, info in statuses.items():
                status = info.get("status", "UNKNOWN")
                if status == "RUNNING":
                    running += 1
                elif status == "CRASHED":
                    crashed += 1
                elif status == "UNRESPONSIVE":
                    unresponsive += 1

                agent_details.append({
                    "agent_id": aid,
                    "status": status,
                    "department": info.get("department", ""),
                    "retries": info.get("retries", 0),
                    "last_heartbeat": info.get("last_heartbeat", ""),
                })
        else:
            total_agents = len(self._agent_health)
            for ah in self._agent_health.values():
                if ah.status == "RUNNING":
                    running += 1
                elif ah.status in ("CRASHED", "DEAD"):
                    crashed += 1

        # Kill switch status
        kill_switch = False
        try:
            from app.core.kv_store import get_kv_store
            val = await get_kv_store().get("horizon:system:kill_switch")
            kill_switch = val == "1"
        except Exception:
            pass

        # Data freshness
        data_freshness = 0.0
        last_ingestion = ""
        ohlcv_count = 0
        try:
            async with _get_session_factory()() as session:
                row = await session.execute(
                    sa_text("SELECT MAX(created_at) FROM ohlcv")
                )
                result = row.fetchone()
                if result and result[0]:
                    raw = result[0]
                    last_ingestion = str(raw)
                    try:
                        if isinstance(raw, datetime):
                            dt = raw
                        else:
                            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        data_freshness = max(
                            0.0, (now_utc - dt).total_seconds()
                        )
                    except (ValueError, TypeError):
                        pass

                count_row = await session.execute(
                    sa_text("SELECT COUNT(DISTINCT symbol) FROM ohlcv")
                )
                cr = count_row.fetchone()
                ohlcv_count = int(cr[0]) if cr else 0
        except Exception:
            pass

        snapshot = SystemHealthSnapshot(
            timestamp=now_utc.isoformat(),
            total_agents=total_agents,
            agents_running=running,
            agents_crashed=crashed,
            agents_unresponsive=unresponsive,
            messages_per_minute=round(mpm, 1),
            avg_message_latency_ms=round(
                float(np.mean(list(self._message_latencies))) * 1000
                if self._message_latencies else 0.0, 2
            ),
            memory_usage_mb=round(memory_mb, 1),
            cpu_percent=round(cpu_pct, 1),
            uptime_hours=round((now - self._start_time) / 3600, 2),
            last_data_ingestion=last_ingestion,
            data_freshness_seconds=round(data_freshness, 1),
            ohlcv_symbols_tracked=ohlcv_count,
            kill_switch_active=kill_switch,
            agent_details=agent_details,
        )

        return snapshot

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_uptime(self) -> float:
        """Return system uptime in hours."""
        return (time.time() - self._start_time) / 3600

    def get_message_stats(self) -> dict:
        """Return message bus statistics."""
        now = time.time()
        last_min = sum(1 for t in self._message_timestamps if t > now - 60)
        last_hour = sum(1 for t in self._message_timestamps if t > now - 3600)

        return {
            "total_messages": self._total_messages,
            "messages_per_minute": last_min,
            "messages_per_hour": last_hour,
            "total_errors": self._total_errors,
        }

    def get_snapshot_history(self, limit: int = 60) -> list[dict]:
        """Return recent health snapshots."""
        return [
            {
                "timestamp": s.timestamp,
                "agents_running": s.agents_running,
                "agents_total": s.total_agents,
                "messages_per_minute": s.messages_per_minute,
                "memory_mb": s.memory_usage_mb,
                "uptime_hours": s.uptime_hours,
            }
            for s in self._snapshots[-limit:]
        ]

    def to_rich_text(self, snapshot: SystemHealthSnapshot) -> str:
        """Format health snapshot as Rich terminal markup."""
        # Agent status indicator
        if snapshot.agents_crashed > 0:
            agent_status = "[red]DEGRADED[/]"
        elif snapshot.agents_unresponsive > 0:
            agent_status = "[yellow]WARNING[/]"
        else:
            agent_status = "[green]HEALTHY[/]"

        lines = [
            f"[bold cyan]System Health[/bold cyan]  {agent_status}",
            "",
            "[bold]Agents:[/]",
            f"  Running:        {snapshot.agents_running}/{snapshot.total_agents}",
            f"  Crashed:        {snapshot.agents_crashed}",
            f"  Unresponsive:   {snapshot.agents_unresponsive}",
            "",
            "[bold]Message Bus:[/]",
            f"  Throughput:     {snapshot.messages_per_minute:.0f} msg/min",
            f"  Avg Latency:    {snapshot.avg_message_latency_ms:.1f} ms",
            "",
            "[bold]System:[/]",
            f"  Memory:         {snapshot.memory_usage_mb:.0f} MB",
            f"  CPU:            {snapshot.cpu_percent:.1f}%",
            f"  Uptime:         {snapshot.uptime_hours:.1f} hours",
            "",
            "[bold]Data Pipeline:[/]",
            f"  Symbols Tracked: {snapshot.ohlcv_symbols_tracked}",
            f"  Last Ingestion:  "
            f"{snapshot.last_data_ingestion[:19] if snapshot.last_data_ingestion else 'N/A'}",
            f"  Data Age:        "
            f"{_format_age(snapshot.data_freshness_seconds) if snapshot.last_data_ingestion else 'N/A'}",
            "",
            f"  Kill Switch:    "
            f"{'[red]ACTIVE[/]' if snapshot.kill_switch_active else '[green]OFF[/]'}",
        ]

        if snapshot.agent_details:
            lines.append("")
            lines.append("[bold]Agent Details:[/]")
            for ad in snapshot.agent_details:
                status = ad["status"]
                if status == "RUNNING":
                    color = "green"
                elif status in ("CRASHED", "DEAD"):
                    color = "red"
                else:
                    color = "yellow"
                dept = ad.get("department", "")
                retries = ad.get("retries", 0)
                lines.append(
                    f"  [{color}]{ad['agent_id']:25s} "
                    f"{status:14s}[/] "
                    f"dept={dept:15s} restarts={retries}"
                )

        return "\n".join(lines)


def _get_session_factory():
    from app.core.runtime import get_session_factory
    return get_session_factory()


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"
