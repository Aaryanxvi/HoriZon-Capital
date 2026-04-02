"""Pixel Agent Visualizer — animated ASCII characters for each agent.

Inspired by pablodelucca/pixel-agents. Each agent is represented as a small
pixel-art character in the terminal using Unicode block/braille characters.
Characters animate based on actual agent state (analyzing, debating, executing,
idle) and are colored by department.

The agents inhabit a terminal "office" layout with desks, and their activity
is shown via animation frames and speech bubbles.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.panel import Panel
from rich.text import Text

# ---------------------------------------------------------------------------
# Pixel art character frames (5x3 grid using Unicode block characters)
# Each frame is a list of 3 strings (top, mid, bottom rows)
# ---------------------------------------------------------------------------

# Character sprites by state — uses Unicode block chars for pixel look
SPRITES: dict[str, list[list[str]]] = {
    "IDLE": [
        # Frame 0
        [
            "  o  ",
            " /|\\ ",
            " / \\ ",
        ],
        # Frame 1 (slight sway)
        [
            "  o  ",
            " /|\\ ",
            " / \\ ",
        ],
    ],
    "ANALYZING": [
        # Frame 0 — looking at screen
        [
            "  o  ",
            " /|\\>",
            " / \\ ",
        ],
        # Frame 1 — typing
        [
            "  o  ",
            " /|=|",
            " / \\ ",
        ],
        # Frame 2
        [
            "  o  ",
            " /|\\>",
            " / \\ ",
        ],
    ],
    "DEBATING": [
        # Frame 0 — arm raised
        [
            "  o/ ",
            " /|  ",
            " / \\ ",
        ],
        # Frame 1 — both arms
        [
            " \\o/ ",
            "  |  ",
            " / \\ ",
        ],
        # Frame 2
        [
            "  o/ ",
            " /|  ",
            " / \\ ",
        ],
    ],
    "EXECUTING": [
        # Frame 0 — running
        [
            "  o  ",
            "  |> ",
            " / > ",
        ],
        # Frame 1
        [
            "  o  ",
            " <|  ",
            " < \\ ",
        ],
    ],
    "STOPPED": [
        [
            "  x  ",
            " /|\\ ",
            " / \\ ",
        ],
    ],
    "CRASHED": [
        [
            " _o_ ",
            " /|\\ ",
            "  |  ",
        ],
    ],
}

# Department color schemes
DEPT_COLORS: dict[str, str] = {
    "front_office": "bright_blue",
    "middle_office": "bright_yellow",
    "back_office": "bright_magenta",
    "executive": "bright_red",
    "": "white",
}

# Activity bubbles (shown above agent)
BUBBLES: dict[str, str] = {
    "ANALYZING": "...",
    "DEBATING": "!?",
    "EXECUTING": ">>",
    "IDLE": "zz",
    "STOPPED": "--",
    "CRASHED": "XX",
}

# Desk art
DESK = [
    " _____ ",
    "|_____|",
]


@dataclass
class PixelAgent:
    """A single pixel agent with animation state."""

    agent_id: str
    short_name: str  # e.g., "REGIME" for "regime-agent"
    department: str = ""
    state: str = "IDLE"
    frame_index: int = 0
    last_state_change: float = 0.0


class PixelAgentVisualizer:
    """Renders animated pixel-art agents in the terminal.

    Each agent is drawn as a small ASCII character sitting at a desk,
    with animation frames cycling based on their current state.
    Agents are grouped by department in a grid layout.
    """

    def __init__(self) -> None:
        self._agents: dict[str, PixelAgent] = {}
        self._frame_counter: int = 0
        self._last_frame_time: float = 0.0

    def register_agent(
        self,
        agent_id: str,
        department: str = "",
    ) -> None:
        """Register an agent for visualization."""
        short = self._make_short_name(agent_id)
        self._agents[agent_id] = PixelAgent(
            agent_id=agent_id,
            short_name=short,
            department=department,
        )

    def update_state(self, agent_id: str, state: str, department: str = "") -> None:
        """Update an agent's visual state."""
        if agent_id not in self._agents:
            self.register_agent(agent_id, department)

        agent = self._agents[agent_id]
        state = state.upper()
        if state not in SPRITES:
            # Map common states
            state_map = {
                "RUNNING": "ANALYZING",
                "INIT": "IDLE",
                "DEAD": "CRASHED",
                "UNRESPONSIVE": "STOPPED",
            }
            state = state_map.get(state, "IDLE")

        if state != agent.state:
            agent.frame_index = 0
            agent.last_state_change = time.time()
        agent.state = state
        if department:
            agent.department = department

    def tick(self) -> None:
        """Advance animation frame counter."""
        now = time.time()
        if now - self._last_frame_time >= 0.5:
            self._frame_counter += 1
            self._last_frame_time = now

            # Advance each agent's frame
            for agent in self._agents.values():
                frames = SPRITES.get(agent.state, SPRITES["IDLE"])
                agent.frame_index = self._frame_counter % len(frames)

    def build_panel(self) -> Panel:
        """Build a Rich panel showing the pixel agent office."""
        self.tick()

        if not self._agents:
            return Panel(
                "[dim]No agents registered yet...[/dim]",
                title="[bold]Agent Office[/bold]",
                border_style="cyan",
            )

        # Group agents by department
        by_dept: dict[str, list[PixelAgent]] = {}
        for agent in self._agents.values():
            dept = agent.department or "other"
            if dept not in by_dept:
                by_dept[dept] = []
            by_dept[dept].append(agent)

        text = Text()
        dept_order = ["front_office", "middle_office", "back_office", "executive", "other"]

        for dept in dept_order:
            agents = by_dept.get(dept, [])
            if not agents:
                continue

            color = DEPT_COLORS.get(dept, "white")
            dept_label = dept.replace("_", " ").title()
            text.append(f" {dept_label}\n", style=f"bold {color}")

            # Render agents in rows of 4
            for row_start in range(0, len(agents), 4):
                row_agents = agents[row_start:row_start + 4]
                self._render_agent_row(text, row_agents)

        return Panel(
            text,
            title="[bold]Agent Office[/bold]",
            border_style="cyan",
        )

    def _render_agent_row(self, text: Text, agents: list[PixelAgent]) -> None:
        """Render a row of agents side by side."""
        # Row layout per agent: bubble + 3 sprite lines + desk + name = 7 lines
        cell_width = 12

        # Line 0: Speech bubbles
        for agent in agents:
            bubble = BUBBLES.get(agent.state, "  ")
            text.append(f"   ({bubble})", style="dim")
            padding = cell_width - len(f"   ({bubble})")
            text.append(" " * max(padding, 1))
        text.append("\n")

        # Lines 1-3: Sprite frames
        for line_idx in range(3):
            for agent in agents:
                frames = SPRITES.get(agent.state, SPRITES["IDLE"])
                frame = frames[agent.frame_index % len(frames)]
                sprite_line = frame[line_idx]
                color = DEPT_COLORS.get(agent.department, "white")
                text.append(f"  {sprite_line}", style=color)
                padding = cell_width - len(f"  {sprite_line}")
                text.append(" " * max(padding, 1))
            text.append("\n")

        # Line 4-5: Desk
        for desk_line in DESK:
            for _ in agents:
                text.append(f" {desk_line}", style="dim")
                padding = cell_width - len(f" {desk_line}")
                text.append(" " * max(padding, 1))
            text.append("\n")

        # Line 6: Agent name labels
        for agent in agents:
            name = agent.short_name[:8]
            color = DEPT_COLORS.get(agent.department, "white")
            centered = name.center(cell_width)
            text.append(centered, style=f"bold {color}")
        text.append("\n")

    @staticmethod
    def _make_short_name(agent_id: str) -> str:
        """Convert agent_id to a short display name."""
        # "regime-agent-1" -> "REGIME"
        # "risk-agent" -> "RISK"
        parts = agent_id.replace("_", "-").split("-")
        # Take first meaningful part
        for part in parts:
            if part.lower() not in ("agent", "1", "2", "3", "manager"):
                return part.upper()[:8]
        return agent_id[:8].upper()

    def get_agent_count(self) -> int:
        return len(self._agents)

    def get_states_summary(self) -> dict[str, int]:
        """Return count of agents per state."""
        counts: dict[str, int] = {}
        for agent in self._agents.values():
            counts[agent.state] = counts.get(agent.state, 0) + 1
        return counts
