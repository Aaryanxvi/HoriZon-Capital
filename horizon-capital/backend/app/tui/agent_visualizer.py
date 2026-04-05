"""Visual agent layer — tracks and displays real-time agent activity states.

Each agent can be in one of four states:
  ANALYZING  — processing market data (green)
  DEBATING   — in a debate session (blue)
  EXECUTING  — executing a trade (orange)
  IDLE       — waiting for next cycle (dim)

Agents emit state changes on the ``horizon.agent.state`` channel.
The visualizer renders a color-coded panel in the TUI dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.core.messaging import AgentMessage, MessageType

# Agent activity states and their visual representation
AGENT_STATES = {
    "ANALYZING": ("green", "A"),
    "DEBATING": ("blue", "D"),
    "EXECUTING": ("bright_red", "E"),
    "IDLE": ("dim", "-"),
    "STOPPED": ("red", "X"),
    "UNKNOWN": ("dim", "?"),
}


class AgentVisualizer:
    """Tracks agent activity states and renders a visual grid."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}  # agent_id -> state
        self._last_update: dict[str, str] = {}  # agent_id -> timestamp

    def update_state(self, agent_id: str, state: str) -> None:
        """Update an agent's activity state."""
        state = state.upper()
        if state not in AGENT_STATES:
            state = "UNKNOWN"
        self._states[agent_id] = state
        self._last_update[agent_id] = datetime.now(UTC).isoformat()

    def set_idle(self, agent_id: str) -> None:
        self._states[agent_id] = "IDLE"

    async def on_state_message(self, message: AgentMessage) -> None:
        """Handle agent state change messages from the bus."""
        if message.message_type == MessageType.AGENT_STATUS:
            agent_id = message.payload.get("agent_id", message.sender_id)
            state = message.payload.get("state", "IDLE")
            self.update_state(agent_id, state)

    def build_panel(self) -> Panel:
        """Build a Rich panel showing agent states as a color-coded grid."""
        if not self._states:
            return Panel(
                "[dim]Awaiting agent activity...[/dim]",
                title="[bold]Agent Activity[/bold]",
                border_style="cyan",
            )

        table = Table(show_header=True, header_style="bold cyan", expand=True, padding=(0, 1))
        table.add_column("Agent", width=22)
        table.add_column("State", width=12)
        table.add_column("", width=3)  # indicator

        for agent_id in sorted(self._states.keys()):
            state = self._states[agent_id]
            color, indicator = AGENT_STATES.get(state, ("dim", "?"))
            state_text = Text(state, style=color)
            indicator_text = Text(f" {indicator} ", style=f"bold {color}")
            table.add_row(agent_id, state_text, indicator_text)

        # Legend
        legend = Text()
        legend.append("  ")
        for state_name, (color, ind) in AGENT_STATES.items():
            if state_name in ("UNKNOWN",):
                continue
            legend.append(f" {ind}", style=f"bold {color}")
            legend.append(f"={state_name}", style="dim")

        lines_text = Text()
        lines_text.append_text(legend)

        return Panel(
            table,
            title="[bold]Agent Activity[/bold]",
            subtitle=str(legend),
            border_style="cyan",
        )

    def get_states(self) -> dict[str, str]:
        """Return current state map for all tracked agents."""
        return dict(self._states)
