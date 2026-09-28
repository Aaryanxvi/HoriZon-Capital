# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D32CC100C65C
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Interactive settings panel for Horizon Capital.

Invoked via the ``settings`` REPL command. Temporarily pauses the Rich Live
dashboard, shows a full-screen interactive form for editing API keys,
AI allocation, and debate role assignments, then resumes the dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from app.core.logging import get_logger

logger = get_logger("tui.settings_panel")

# Map of .env key name -> display label
_API_KEY_FIELDS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY",  "Claude (Anthropic)"),
    ("OPENAI_API_KEY",     "OpenAI (GPT-4)"),
    ("GOOGLE_API_KEY",     "Google (Gemini)"),
    ("ALPACA_API_KEY",     "Alpaca API Key"),
    ("ALPACA_API_SECRET",  "Alpaca API Secret"),
    ("NEWSAPI_API_KEY",    "NewsAPI"),
    ("POLYGON_API_KEY",    "Polygon"),
]

_AI_ALLOCATION_FIELDS: list[tuple[str, str]] = [
    ("AI_FRONT_OFFICE",  "Front Office"),
    ("AI_MIDDLE_OFFICE", "Middle Office"),
    ("AI_BACK_OFFICE",   "Back Office"),
    ("AI_EXECUTIVE",     "Executive / CIO"),
]

_DEBATE_ROLE_FIELDS: list[tuple[str, str]] = [
    ("DEBATE_ROLE_STRATEGY",  "Strategy (bull case)"),
    ("DEBATE_ROLE_RISK",      "Risk (bear case)"),
    ("DEBATE_ROLE_SENTIMENT", "Sentiment analyst"),
    ("DEBATE_ROLE_PORTFOLIO", "Portfolio fit"),
]

_PROVIDER_CHOICES = ["auto", "claude", "openai", "gemini", "none"]
_DEBATE_CHOICES = ["auto", "claude", "openai", "gemini"]


def _mask(value: str) -> str:
    """Mask all but the last 4 chars of a secret value."""
    if not value or len(value) <= 4:
        return "----" if value else "(not set)"
    return "----" + value[-4:]


def _read_env(env_path: str) -> dict[str, str]:
    """Parse a .env file into a key->value dict."""
    result: dict[str, str] = {}
    try:
        for line in Path(env_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                result[k.strip().upper()] = v.strip()
    except FileNotFoundError:
        pass
    return result


def _write_env_key(env_path: str, key: str, value: str) -> None:
    """Update or append a single key=value pair in the .env file."""
    path = Path(env_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    key_upper = key.upper()
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key_upper}=") or stripped.startswith(f"{key_upper} ="):
            new_lines.append(f"{key_upper}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key_upper}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class SettingsPanel:
    """Interactive settings editor rendered in the terminal."""

    def __init__(self, registry, env_path: str = ".env") -> None:
        self._registry = registry
        self._env_path = env_path

    def run(self, console: Console) -> None:
        """Run the interactive settings form (blocking, for use in REPL)."""
        console.rule("[bold cyan]Horizon Capital -- Settings[/bold cyan]")
        console.print()

        while True:
            tab = Prompt.ask(
                "  Select tab",
                choices=["keys", "allocation", "debate", "done"],
                default="keys",
                console=console,
            )
            console.print()

            if tab == "done":
                console.print("[green]Settings saved.[/green]\n")
                break
            elif tab == "keys":
                self._edit_api_keys(console)
            elif tab == "allocation":
                self._edit_ai_allocation(console)
            elif tab == "debate":
                self._edit_debate_roles(console)

        # Hot-reload provider registry with any updated keys
        self._registry.reload_from_settings()

    def _edit_api_keys(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="API Keys", show_header=True)
        table.add_column("Provider", style="cyan")
        table.add_column("Current Value", style="dim")

        for env_key, label in _API_KEY_FIELDS:
            current = env.get(env_key, "")
            table.add_row(label, _mask(current))

        console.print(table)
        console.print()

        field_label = Prompt.ask(
            "  Edit key for (or [dim]skip[/dim])",
            choices=[label for _, label in _API_KEY_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if field_label == "skip":
            return

        env_key = next(k for k, lbl in _API_KEY_FIELDS if lbl == field_label)
        new_value = Prompt.ask(
            f"  Enter new value for [cyan]{field_label}[/cyan]",
            console=console,
            password=True,
        )

        if not new_value.strip():
            console.print("[yellow]  Empty value -- key cleared.[/yellow]")
            new_value = ""

        if self._save_key(env_key, new_value):
            self._apply_to_settings(env_key, new_value)
            console.print(f"[green]  {field_label} updated.[/green]")
        else:
            console.print("[red]  Key validation failed -- .env not updated.[/red]")

    def _edit_ai_allocation(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="AI Department Allocation", show_header=True)
        table.add_column("Department", style="cyan")
        table.add_column("Current Provider", style="yellow")
        table.add_column("Options", style="dim")

        for env_key, label in _AI_ALLOCATION_FIELDS:
            current = env.get(env_key, "auto")
            table.add_row(label, current, " / ".join(_PROVIDER_CHOICES))

        console.print(table)
        console.print()

        dept_label = Prompt.ask(
            "  Update allocation for (or [dim]skip[/dim])",
            choices=[lbl for _, lbl in _AI_ALLOCATION_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if dept_label == "skip":
            return

        env_key = next(k for k, lbl in _AI_ALLOCATION_FIELDS if lbl == dept_label)
        new_value = Prompt.ask(
            f"  Provider for [cyan]{dept_label}[/cyan]",
            choices=_PROVIDER_CHOICES,
            default="auto",
            console=console,
        )

        _write_env_key(self._env_path, env_key, new_value)
        self._apply_to_settings(env_key, new_value)
        console.print(f"[green]  {dept_label} -> {new_value}[/green]")

    def _edit_debate_roles(self, console: Console) -> None:
        env = _read_env(self._env_path)

        table = Table(title="Debate Role Assignment", show_header=True)
        table.add_column("Role", style="cyan")
        table.add_column("Current Provider", style="yellow")
        table.add_column("Options", style="dim")

        for env_key, label in _DEBATE_ROLE_FIELDS:
            current = env.get(env_key, "auto")
            table.add_row(label, current, " / ".join(_DEBATE_CHOICES))

        console.print(table)
        console.print()
        console.print("[dim]  'auto' = round-robin across all registered providers[/dim]\n")

        role_label = Prompt.ask(
            "  Edit role (or [dim]skip[/dim])",
            choices=[lbl for _, lbl in _DEBATE_ROLE_FIELDS] + ["skip"],
            default="skip",
            console=console,
        )
        if role_label == "skip":
            return

        env_key = next(k for k, lbl in _DEBATE_ROLE_FIELDS if lbl == role_label)
        new_value = Prompt.ask(
            f"  Provider for [cyan]{role_label}[/cyan]",
            choices=_DEBATE_CHOICES,
            default="auto",
            console=console,
        )

        _write_env_key(self._env_path, env_key, new_value)
        self._apply_to_settings(env_key, new_value)
        console.print(f"[green]  {role_label} -> {new_value}[/green]")

    def _validate_key(self, env_key: str, value: str) -> bool:
        """Basic structural validation for well-known key formats."""
        if not value:
            return True

        patterns: dict[str, re.Pattern] = {
            "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-"),
            "OPENAI_API_KEY":    re.compile(r"^sk-"),
            "GOOGLE_API_KEY":    re.compile(r"^AI"),
        }
        pattern = patterns.get(env_key)
        if pattern and not pattern.match(value):
            return False
        return True

    def _save_key(self, env_key: str, value: str) -> bool:
        """Validate then write a single key to .env. Returns True on success."""
        if value and not self._validate_key(env_key, value):
            return False
        try:
            _write_env_key(self._env_path, env_key, value)
            return True
        except Exception as exc:
            logger.error("settings_panel.save_key_error", key=env_key, error=str(exc))
            return False

    def _apply_to_settings(self, env_key: str, value: str) -> None:
        """Mutate the live settings object so changes take effect immediately."""
        from app.config import settings

        field_map: dict[str, str] = {
            "ANTHROPIC_API_KEY":  "anthropic_api_key",
            "OPENAI_API_KEY":     "openai_api_key",
            "GOOGLE_API_KEY":     "google_api_key",
            "ALPACA_API_KEY":     "alpaca_api_key",
            "ALPACA_API_SECRET":  "alpaca_api_secret",
            "NEWSAPI_API_KEY":    "newsapi_api_key",
            "POLYGON_API_KEY":    "polygon_api_key",
            "AI_FRONT_OFFICE":    "ai_front_office",
            "AI_MIDDLE_OFFICE":   "ai_middle_office",
            "AI_BACK_OFFICE":     "ai_back_office",
            "AI_EXECUTIVE":       "ai_executive",
            "DEBATE_ROLE_STRATEGY":  "debate_role_strategy",
            "DEBATE_ROLE_RISK":      "debate_role_risk",
            "DEBATE_ROLE_SENTIMENT": "debate_role_sentiment",
            "DEBATE_ROLE_PORTFOLIO": "debate_role_portfolio",
        }
        attr = field_map.get(env_key.upper())
        if attr and hasattr(settings, attr):
            try:
                object.__setattr__(settings, attr, value)
            except Exception:
                pass
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D32CC100C65C - verify with scripts/authorship.py verify
