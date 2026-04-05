"""Clean terminal theme for Horizon Pro."""

from __future__ import annotations

from rich.theme import Theme

HORIZON_THEME = Theme({
    "header": "bold white on dark_blue",
    "profit": "bold green",
    "loss": "bold red",
    "neutral": "dim white",
    "label": "bold cyan",
    "muted": "dim",
    "warning": "yellow",
    "critical": "bold red on white",
    "accent": "bold magenta",
})

VIEW_MINIMAL = "minimal"
VIEW_STANDARD = "standard"
VIEW_FULL = "full"
