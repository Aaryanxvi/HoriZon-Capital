"""Rich-based terminal dashboard for Horizon Capital.

Renders a live-updating TUI showing:
  - System status bar (mode, storage backend, uptime, CIO mode)
  - Agent status table grouped by department
  - Recent signals
  - Current regime per market scope
  - Risk metrics snapshot
  - Recent debate summaries
  - Live log tail
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.config import settings


DEPARTMENT_COLORS = {
    "front_office": "bright_blue",
    "middle_office": "bright_yellow",
    "back_office": "bright_magenta",
    "executive": "bright_red",
}

DEPARTMENT_LABELS = {
    "front_office": "Front Office",
    "middle_office": "Middle Office",
    "back_office": "Back Office",
    "executive": "Executive",
}


class TerminalDashboard:
    """Live terminal dashboard that polls system state and renders with Rich."""

    def __init__(self) -> None:
        self.console = Console()
        self._running = False
        self._agent_statuses: dict[str, dict[str, Any]] = {}
        self._signals: list[dict[str, Any]] = []
        self._regimes: dict[str, dict[str, Any]] = {}
        self._risk: dict[str, Any] = {}
        self._debates: list[dict[str, Any]] = []
        self._logs: list[str] = []
        self._start_time: datetime = datetime.now(timezone.utc)
        self._portfolio: dict[str, Any] = {"nav": 0.0, "cash": 0.0, "positions": 0}

    # -- Data update methods (called by the orchestrator) ----------------

    def update_agent_status(self, agent_id: str, status: dict[str, Any]) -> None:
        self._agent_statuses[agent_id] = status

    def add_signal(self, signal: dict[str, Any]) -> None:
        self._signals.insert(0, signal)
        self._signals = self._signals[:20]  # keep last 20

    def update_regime(self, scope: str, data: dict[str, Any]) -> None:
        self._regimes[scope] = data

    def update_risk(self, data: dict[str, Any]) -> None:
        self._risk = data

    def add_debate(self, debate: dict[str, Any]) -> None:
        self._debates.insert(0, debate)
        self._debates = self._debates[:10]

    def add_log(self, line: str) -> None:
        self._logs.append(line)
        self._logs = self._logs[-30:]  # keep last 30

    def update_portfolio(self, data: dict[str, Any]) -> None:
        self._portfolio = data

    # -- Layout builders -------------------------------------------------

    def _build_header(self) -> Panel:
        uptime = datetime.now(timezone.utc) - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        mode_colors = {
            "PAPER_TRADING": "yellow",
            "HUMAN_APPROVAL": "cyan",
            "FULLY_AUTONOMOUS": "red",
        }
        mode = settings.system_mode.value
        mode_color = mode_colors.get(mode, "white")

        header = Text()
        header.append("HORIZON CAPITAL ", style="bold white")
        header.append("v0.2.0 ", style="dim")
        header.append(" | ", style="dim")
        header.append("Mode: ", style="white")
        header.append(f"{mode}", style=f"bold {mode_color}")
        header.append(" | ", style="dim")
        header.append("CIO: ", style="white")
        cio_mode = settings.cio_mode.value
        cio_color = "cyan" if cio_mode == "HUMAN" else "bright_red"
        header.append(f"{cio_mode}", style=f"bold {cio_color}")
        header.append(" | ", style="dim")
        header.append("Storage: ", style="white")
        header.append(f"{settings.storage_backend.value}", style="green")
        header.append(" | ", style="dim")
        header.append("Uptime: ", style="white")
        header.append(f"{hours:02d}:{minutes:02d}:{seconds:02d}", style="cyan")
        header.append(" | ", style="dim")
        header.append("NAV: ", style="white")
        header.append(f"${self._portfolio.get('nav', 0.0):,.2f}", style="bold green")

        return Panel(header, style="blue", height=3)

    def _build_agents_table(self) -> Panel:
        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Agent", style="white", width=22)
        table.add_column("Dept", width=14)
        table.add_column("Status", width=12)
        table.add_column("Heartbeat", width=12)
        table.add_column("Retries", width=8, justify="right")

        status_colors = {
            "RUNNING": "green",
            "INIT": "yellow",
            "STOPPED": "red",
            "CRASHED": "bold red",
            "DEAD": "bold red on white",
            "UNRESPONSIVE": "yellow",
        }

        if not self._agent_statuses:
            table.add_row("(no agents registered)", "", "", "", "")
        else:
            # Group by department
            by_dept: dict[str, list[tuple[str, dict]]] = {}
            for agent_id, info in sorted(self._agent_statuses.items()):
                dept = info.get("department", "unassigned")
                if dept not in by_dept:
                    by_dept[dept] = []
                by_dept[dept].append((agent_id, info))

            dept_order = ["front_office", "middle_office", "back_office", "executive"]
            for dept in dept_order:
                agents = by_dept.pop(dept, [])
                if not agents:
                    continue

                # Department header row
                label = DEPARTMENT_LABELS.get(dept, dept)
                color = DEPARTMENT_COLORS.get(dept, "white")
                table.add_row(
                    f"[bold {color}]{label}[/]",
                    "", "", "", "",
                )

                for agent_id, info in agents:
                    status = info.get("status", "UNKNOWN")
                    s_color = status_colors.get(status, "white")
                    hb = info.get("last_heartbeat", "--")
                    if isinstance(hb, str) and len(hb) > 19:
                        hb = hb[11:19]
                    retries = str(info.get("retries", 0))
                    table.add_row(
                        f"  {agent_id}",
                        "",
                        f"[{s_color}]{status}[/]",
                        str(hb),
                        retries,
                    )

            # Any remaining (unassigned)
            for dept, agents in by_dept.items():
                for agent_id, info in agents:
                    status = info.get("status", "UNKNOWN")
                    s_color = status_colors.get(status, "white")
                    hb = info.get("last_heartbeat", "--")
                    if isinstance(hb, str) and len(hb) > 19:
                        hb = hb[11:19]
                    retries = str(info.get("retries", 0))
                    table.add_row(agent_id, dept, f"[{s_color}]{status}[/]", str(hb), retries)

        return Panel(table, title="[bold]Agents[/bold]", border_style="cyan")

    def _build_regime_panel(self) -> Panel:
        if not self._regimes:
            return Panel("Awaiting regime data...", title="[bold]Market Regimes[/bold]",
                         border_style="magenta")

        lines: list[str] = []
        regime_colors = {
            "BULL": "green",
            "BEAR": "red",
            "NEUTRAL": "yellow",
            "CRISIS": "bold red",
            "HIGH_VOLATILITY": "magenta",
        }
        for scope in ["INDIA", "US", "CRYPTO"]:
            data = self._regimes.get(scope, {})
            regime = data.get("regime", "--")
            conf = data.get("confidence", 0.0)
            drift = data.get("drift_level", "NONE")
            color = regime_colors.get(regime, "white")
            drift_indicator = " [yellow]![/yellow]" if drift == "WARNING" else ""
            drift_indicator = " [red]!![/red]" if drift == "DRIFT" else drift_indicator
            lines.append(
                f"  [{color}]{scope:8s}[/] [{color}]{regime:16s}[/] "
                f"conf={conf:.1%}{drift_indicator}"
            )

        return Panel("\n".join(lines), title="[bold]Market Regimes[/bold]",
                     border_style="magenta")

    def _build_signals_panel(self) -> Panel:
        if not self._signals:
            return Panel("No signals yet...", title="[bold]Recent Signals[/bold]",
                         border_style="green")

        table = Table(show_header=True, header_style="bold green", expand=True)
        table.add_column("Time", width=8)
        table.add_column("Symbol", width=14)
        table.add_column("Dir", width=5)
        table.add_column("Str", width=6, justify="right")
        table.add_column("Strategy", width=16)

        for sig in self._signals[:8]:
            ts = sig.get("timestamp", "")
            if isinstance(ts, str) and len(ts) > 19:
                ts = ts[11:19]
            symbol = sig.get("symbol", "--")
            direction = sig.get("direction", 0)
            dir_str = "[green]BUY[/]" if direction > 0 else "[red]SELL[/]" if direction < 0 else "HOLD"
            strength = f"{sig.get('strength', 0.0):.2f}"
            strategy = sig.get("strategy_name", "--")
            table.add_row(str(ts), symbol, dir_str, strength, strategy)

        return Panel(table, title="[bold]Recent Signals[/bold]", border_style="green")

    def _build_risk_panel(self) -> Panel:
        if not self._risk:
            return Panel("Awaiting risk computation...", title="[bold]Risk Metrics[/bold]",
                         border_style="red")

        var_95 = self._risk.get("var_95", 0.0)
        var_99 = self._risk.get("var_99", 0.0)
        max_dd = self._risk.get("max_drawdown", 0.0)
        curr_dd = self._risk.get("current_drawdown", 0.0)
        kill = self._risk.get("kill_switch_active", False)

        kill_str = "[bold red]ACTIVE[/bold red]" if kill else "[green]OFF[/green]"
        dd_color = "red" if curr_dd > 5.0 else "yellow" if curr_dd > 2.0 else "green"

        lines = [
            f"  VaR (95%)   : {var_95:>8.4f}",
            f"  VaR (99%)   : {var_99:>8.4f}",
            f"  Max Drawdown: {max_dd:>8.2f}%",
            f"  Curr Drawdown: [{dd_color}]{curr_dd:>7.2f}%[/]",
            f"  Kill Switch : {kill_str}",
        ]
        return Panel("\n".join(lines), title="[bold]Risk Metrics[/bold]",
                     border_style="red")

    def _build_debates_panel(self) -> Panel:
        if not self._debates:
            return Panel("No debates yet...", title="[bold]Debates[/bold]",
                         border_style="yellow")

        lines: list[str] = []
        for d in self._debates[:5]:
            symbol = d.get("symbol", "--")
            consensus = d.get("consensus", "--")
            conf = d.get("consensus_confidence", 0.0)
            rounds = d.get("rounds", 0)
            color = "green" if consensus in ("BUY", "STRONG_BUY") else \
                    "red" if consensus in ("SELL", "STRONG_SELL") else "yellow"
            lines.append(
                f"  {symbol:12s} [{color}]{consensus:12s}[/] "
                f"conf={conf:.1%}  rounds={rounds}"
            )

        return Panel("\n".join(lines), title="[bold]Debates[/bold]",
                     border_style="yellow")

    def _build_log_panel(self) -> Panel:
        if not self._logs:
            return Panel("...", title="[bold]Log[/bold]", border_style="dim")
        text = "\n".join(self._logs[-12:])
        return Panel(text, title="[bold]Log[/bold]", border_style="dim")

    def build_layout(self) -> Layout:
        """Compose the full dashboard layout."""
        layout = Layout()
        layout.split_column(
            Layout(self._build_header(), name="header", size=3),
            Layout(name="body"),
            Layout(self._build_log_panel(), name="logs", size=14),
        )

        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        layout["left"].split_column(
            Layout(self._build_agents_table(), name="agents"),
            Layout(self._build_signals_panel(), name="signals"),
        )

        layout["right"].split_column(
            Layout(self._build_regime_panel(), name="regime", size=7),
            Layout(self._build_risk_panel(), name="risk", size=9),
            Layout(self._build_debates_panel(), name="debates"),
        )

        return layout

    # -- Run loop --------------------------------------------------------

    async def run(self) -> None:
        """Start the live dashboard. Blocks until stopped."""
        self._running = True
        self._start_time = datetime.now(timezone.utc)

        with Live(
            self.build_layout(),
            console=self.console,
            refresh_per_second=2,
            screen=True,
        ) as live:
            while self._running:
                live.update(self.build_layout())
                await asyncio.sleep(0.5)

    def stop(self) -> None:
        """Signal the dashboard to stop."""
        self._running = False
