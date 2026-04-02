"""First-run onboarding wizard for Horizon Capital.

Inspired by OpenClaw's interactive setup flow. Launches on first run when
no API keys are configured. Guides the user through LLM provider setup,
broker configuration, risk parameters, and system mode selection.

Uses Rich for all UI rendering (prompts, panels, progress bars).
"""

from __future__ import annotations

import asyncio
import io
import random
import sys
import time
from pathlib import Path
from typing import Any


def _ensure_utf8() -> None:
    """Ensure UTF-8 output on Windows. Only call when actually running the TUI."""
    if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import Progress, SpinnerColumn, TextColumn  # noqa: E402
from rich.prompt import Confirm, Prompt  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

console = Console()

VERSION = "0.1.0"

BANNER_LINES = [
    "  ╦ ╦┌─┐┬─┐┬┌─┐┌─┐┌┐┌  ╔═╗┌─┐┌─┐┬┌┬┐┌─┐┬  ",
    "  ╠═╣│ │├┬┘│┌─┘│ ││││  ║  ├─┤├─┘│ │ ├─┤│  ",
    "  ╩ ╩└─┘┴└─┴└─┘└─┘┘└┘  ╚═╝┴ ┴┴  ┴ ┴ ┴ ┴┴─┘",
]

# Characters used in the matrix rain effect
_MATRIX_CHARS = list("0123456789$%&AAPL MSFT GOOGL TSLA BTC ETH ╋╪═║▓░▒█")
_MATRIX_TICKERS = ["AAPL", "MSFT", "GOOG", "TSLA", "AMZN", "BTC", "ETH", "SPY", "QQQ", "NVDA"]

# Boot sequence messages
_BOOT_STEPS = [
    ("Neural network cores", "online"),
    ("Market data feeds", "connected"),
    ("Risk management engine", "armed"),
    ("Trading algorithms", "loaded"),
    ("Portfolio optimizer", "ready"),
]

# Candlestick chart data (height values 1-8, positive=green, negative=red)
_CANDLE_DATA = [
    (3, 5, True), (4, 6, True), (5, 3, False), (3, 4, True),
    (4, 2, False), (2, 5, True), (5, 7, True), (6, 4, False),
    (4, 6, True), (6, 8, True), (7, 5, False), (5, 7, True),
    (7, 9, True),  # final candle shoots up
]


def _matrix_rain(duration: float = 2.0) -> None:
    """Phase 1: Matrix-style market data rain."""
    width = min(console.width, 80)
    height = 16
    fps = 20
    ticks = int(duration * fps)

    # Each column tracks: current char, brightness (0-5), speed
    columns: list[dict[str, Any]] = []
    for c in range(width):
        columns.append({
            "chars": [" "] * height,
            "bright": [0] * height,
            "drop_y": random.randint(-height, 0),
            "speed": random.uniform(0.3, 1.0),
            "active": random.random() < 0.4,
        })

    with Live(console=console, refresh_per_second=fps, screen=False) as live:
        for tick in range(ticks):
            # Update columns
            for col in columns:
                if not col["active"] and random.random() < 0.05:
                    col["active"] = True
                    col["drop_y"] = -1
                    col["speed"] = random.uniform(0.3, 1.0)

                if col["active"]:
                    col["drop_y"] += col["speed"]
                    y = int(col["drop_y"])
                    if 0 <= y < height:
                        # New character at the drop point
                        if random.random() < 0.3:
                            col["chars"][y] = random.choice(_MATRIX_TICKERS)[:1]
                        else:
                            col["chars"][y] = random.choice(_MATRIX_CHARS)
                        col["bright"][y] = 5  # max brightness
                    if y >= height + 4:
                        col["active"] = False

                # Fade all cells
                for r in range(height):
                    if col["bright"][r] > 0:
                        col["bright"][r] = max(0, col["bright"][r] - 0.15)
                    if col["bright"][r] <= 0:
                        col["chars"][r] = " "

            # Render frame
            lines = []
            for r in range(height):
                row_text = Text()
                for col in columns:
                    ch = col["chars"][r]
                    b = col["bright"][r]
                    if b > 4:
                        row_text.append(ch, style="bold bright_green")
                    elif b > 3:
                        row_text.append(ch, style="green")
                    elif b > 1.5:
                        row_text.append(ch, style="dark_green")
                    elif b > 0:
                        row_text.append(ch, style="dim green")
                    else:
                        row_text.append(" ")
                lines.append(row_text)

            # Assemble
            output = Text()
            for i, line in enumerate(lines):
                output.append_text(line)
                if i < len(lines) - 1:
                    output.append("\n")
            live.update(output)
            time.sleep(1.0 / fps)


def _typing_logo(duration: float = 1.5) -> None:
    """Phase 2: Logo reveals with a typing cursor effect."""
    fps = 30
    # Type out each banner line character by character
    all_lines = BANNER_LINES
    total_chars = sum(len(line) for line in all_lines)
    chars_per_sec = total_chars / duration

    with Live(console=console, refresh_per_second=fps, screen=False) as live:
        revealed = 0
        for line_idx, line in enumerate(all_lines):
            for char_idx in range(len(line)):
                revealed += 1
                # Build current display
                output = Text()
                output.append("\n")
                for li in range(line_idx + 1):
                    if li < line_idx:
                        # Fully revealed lines
                        output.append(all_lines[li], style="bold cyan")
                    else:
                        # Current line up to char_idx
                        output.append(line[:char_idx + 1], style="bold cyan")
                        output.append("█", style="bold white")  # cursor
                    output.append("\n")
                live.update(output)
                time.sleep(1.0 / chars_per_sec)

        # Final reveal — remove cursor, add tagline
        output = Text()
        output.append("\n")
        for line in all_lines:
            output.append(line, style="bold cyan")
            output.append("\n")
        output.append("  Autonomous AI Hedge Fund Terminal Agent", style="dim")
        output.append(f"  v{VERSION}", style="dim italic")
        output.append("\n")
        live.update(output)
        time.sleep(0.3)


def _boot_sequence(duration: float = 2.0) -> None:
    """Phase 3: Fake system boot sequence with spinners resolving to checkmarks."""
    delay_per_step = duration / len(_BOOT_STEPS)
    spinner_chars = ["|", "/", "-", "\\"]
    fps = 15

    completed: list[tuple[str, str]] = []

    def _build_output(
        current_label: str | None = None, current_dots: str = "", spinner_ch: str = ""
    ) -> Text:
        output = Text()
        for prev_label, prev_status in completed:
            prev_dots = "." * (35 - len(prev_label))
            output.append("  [", style="dim")
            output.append("v", style="bold green")
            output.append("] ", style="dim")
            output.append(f"{prev_label}{prev_dots} ", style="white")
            output.append(prev_status, style="bold green")
            output.append("\n")
        if current_label is not None:
            output.append("  [", style="dim")
            output.append(spinner_ch, style="bold cyan")
            output.append("] ", style="dim")
            output.append(f"{current_label}{current_dots} ", style="white")
            output.append("...", style="dim")
            output.append("\n")
        return output

    with Live(console=console, refresh_per_second=fps, screen=False) as live:
        for step_idx, (label, status) in enumerate(_BOOT_STEPS):
            dots = "." * (35 - len(label))
            spin_ticks = int(delay_per_step * fps) + random.randint(-3, 5)

            for t in range(max(spin_ticks, 4)):
                sc = spinner_chars[t % len(spinner_chars)]
                live.update(_build_output(label, dots, sc))
                time.sleep(1.0 / fps)

            completed.append((label, status))
            live.update(_build_output())

    console.print()


def _draw_candle_chart(duration: float = 1.5) -> None:
    """Phase 4: ASCII candlestick chart draws itself left to right."""
    chart_height = 12
    fps = 12
    delay_per_candle = duration / len(_CANDLE_DATA)

    drawn_candles: list[tuple[int, int, bool]] = []

    with Live(console=console, refresh_per_second=fps, screen=False) as live:
        for ci, (low, high, is_green) in enumerate(_CANDLE_DATA):
            drawn_candles.append((low, high, is_green))

            # Animate this candle growing
            grow_frames = max(3, int(delay_per_candle * fps))
            for frame in range(grow_frames):
                progress = (frame + 1) / grow_frames
                output = _render_chart(drawn_candles, chart_height, progress)
                live.update(output)
                time.sleep(1.0 / fps)

        # Final frame with dollar signs on the last candle
        final = _render_chart(drawn_candles, chart_height, 1.0, show_dollars=True)
        live.update(final)
        time.sleep(0.5)


def _render_chart(
    candles: list[tuple[int, int, bool]],
    height: int,
    last_progress: float,
    show_dollars: bool = False,
) -> Text:
    """Render the candlestick chart as a Text object."""
    output = Text()
    output.append("\n")

    # Build grid
    grid = [[" "] * (len(candles) * 4 + 4) for _ in range(height)]
    colors = [[None] * (len(candles) * 4 + 4) for _ in range(height)]

    # Y-axis
    for r in range(height):
        grid[r][0] = "│"
        colors[r][0] = "dim"

    # X-axis
    for c in range(len(candles) * 4 + 4):
        if c < len(grid[0]):
            grid[height - 1][c] = "─"
            colors[height - 1][c] = "dim"
    grid[height - 1][0] = "└"
    colors[height - 1][0] = "dim"

    for ci, (low, high, is_green) in enumerate(candles):
        x = ci * 4 + 2
        color = "green" if is_green else "red"
        style = f"bold {color}"

        # For the last candle, apply growth progress
        if ci == len(candles) - 1:
            effective_high = low + int((high - low) * last_progress)
        else:
            effective_high = high

        for r in range(height):
            y_val = height - 1 - r  # invert so 0 is bottom
            if low <= y_val <= effective_high and x < len(grid[r]):
                if y_val == low or y_val == effective_high:
                    grid[r][x] = "┃"
                else:
                    grid[r][x] = "█"
                colors[r][x] = style

    # Dollar signs on last candle if requested
    if show_dollars and candles:
        last_x = (len(candles) - 1) * 4 + 2
        _, last_high, _ = candles[-1]
        top_row = height - 1 - last_high
        if top_row - 1 >= 0 and last_x + 2 < len(grid[0]):
            for dx in range(-1, 3):
                col = last_x + dx
                if 0 <= col < len(grid[0]) and top_row - 1 >= 0:
                    grid[top_row - 1][col] = "$"
                    colors[top_row - 1][col] = "bold yellow"

    # Render grid to Text
    for r in range(height):
        for c in range(min(len(grid[r]), 60)):
            ch = grid[r][c]
            clr = colors[r][c]
            if clr:
                output.append(ch, style=clr)
            else:
                output.append(ch)
        output.append("\n")

    return output


def _play_intro_animation() -> None:
    """Play the full multi-phase intro animation."""
    console.clear()
    _matrix_rain(duration=2.0)
    console.clear()
    _typing_logo(duration=1.5)
    _boot_sequence(duration=2.0)
    _draw_candle_chart(duration=1.5)


def _step_header(step: int, total: int, title: str) -> None:
    """Render a styled step header with progress bar."""
    filled = step
    empty = total - step
    bar = "█" * filled + "░" * empty

    header = Text()
    header.append(f"\n  {bar}", style="cyan")
    header.append(f"  {step}/{total}", style="bold white")
    header.append(f"  — {title}", style="bold cyan")
    console.print(header)


def _gradient_panel(content: str, title: str = "") -> Panel:
    """Create a panel with a gradient-style border."""
    return Panel(
        content,
        title=f"[bold bright_cyan]◆ {title} ◆[/bold bright_cyan]" if title else None,
        border_style="bright_cyan",
        padding=(1, 3),
        subtitle=f"[dim]v{VERSION}[/dim]",
    )


def _env_path() -> Path:
    """Return the path to the .env file in the backend directory."""
    return Path(__file__).resolve().parent.parent.parent / ".env"


def needs_onboarding() -> bool:
    """Check if we should run the onboarding wizard.

    Returns True if no .env exists or no LLM API keys are configured.
    """
    env_file = _env_path()
    if not env_file.exists():
        return True

    # Check if any LLM key is set
    from app.config import settings
    has_llm = bool(
        settings.anthropic_api_key
        or settings.openai_api_key
        or settings.google_api_key
    )
    return not has_llm


def _select_option(prompt_text: str, options: list[str], default: int = 0) -> int:
    """Simple numbered selection using Rich Prompt."""
    console.print(f"\n[bold]{prompt_text}[/bold]")
    for i, opt in enumerate(options):
        marker = "[green]>[/green]" if i == default else " "
        console.print(f"  {marker} {i + 1}. {opt}")
    choice = Prompt.ask(
        "Select",
        default=str(default + 1),
        choices=[str(i + 1) for i in range(len(options))],
    )
    return int(choice) - 1


def _masked_input(prompt_text: str) -> str:
    """Prompt for a secret value (API key). Returns empty string if skipped."""
    value = Prompt.ask(f"  {prompt_text}", password=True, default="")
    return value.strip()


async def _verify_anthropic_key(key: str) -> bool:
    """Lightweight check for Anthropic API key validity."""
    if not key or len(key) < 10:
        return False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True
    except Exception:
        return False


async def _verify_openai_key(key: str) -> bool:
    """Lightweight check for OpenAI API key validity."""
    if not key or len(key) < 10:
        return False
    try:
        import openai
        client = openai.OpenAI(api_key=key)
        client.models.list()
        return True
    except Exception:
        return False


async def _verify_gemini_key(key: str) -> bool:
    """Lightweight check for Google Gemini API key validity."""
    if not key or len(key) < 10:
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        list(genai.list_models())
        return True
    except Exception:
        return False


async def _verify_alpaca_key(key: str, secret: str) -> bool:
    """Check Alpaca API credentials."""
    if not key or not secret:
        return False
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://paper-api.alpaca.markets/v2/account",
                headers={
                    "APCA-API-KEY-ID": key,
                    "APCA-API-SECRET-KEY": secret,
                },
                timeout=10,
            )
            return resp.status_code == 200
    except Exception:
        return False


def _launch_sequence() -> None:
    """Play a countdown launch animation after user confirms."""
    fps = 4
    countdown = ["3", "2", "1"]
    colors = ["yellow", "bright_yellow", "bright_red"]

    with Live(console=console, refresh_per_second=fps, screen=False) as live:
        for num, color in zip(countdown, colors):
            text = Text()
            text.append(f"\n  {num}...", style=f"bold {color}")
            live.update(text)
            time.sleep(0.7)

    # LAUNCH banner
    rocket = r"""
[bold bright_green]
     ██╗      █████╗ ██╗   ██╗███╗   ██╗ ██████╗██╗  ██╗
     ██║     ██╔══██╗██║   ██║████╗  ██║██╔════╝██║  ██║
     ██║     ███████║██║   ██║██╔██╗ ██║██║     ███████║
     ██║     ██╔══██║██║   ██║██║╚██╗██║██║     ██╔══██║
     ███████╗██║  ██║╚██████╔╝██║ ╚████║╚██████╗██║  ██║
     ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝
[/bold bright_green]
[bold cyan]          🚀  Systems are GO  🚀[/bold cyan]
"""
    console.print(rocket)
    time.sleep(1.0)


_DEPT_LABELS = {
    "front_office": "Front Office  (strategy, regime, sentiment, IR)",
    "middle_office": "Middle Office (debate engine, risk, compliance)",
    "back_office":  "Back Office   (quant research)",
    "executive":    "Executive     (CIO agent)",
}

_DEPT_ENV_KEYS = {
    "front_office": "AI_FRONT_OFFICE",
    "middle_office": "AI_MIDDLE_OFFICE",
    "back_office": "AI_BACK_OFFICE",
    "executive": "AI_EXECUTIVE",
}


def _dept_ai_routing_step(config: dict[str, str], available: list[str]) -> None:
    """Interactive department→AI provider assignment step."""
    provider_list = ["auto (use any available)"] + available + ["none (rule-based only)"]
    provider_map = {0: "auto"}
    for i, p in enumerate(available, start=1):
        provider_map[i] = p
    provider_map[len(available) + 1] = "none"

    console.print(
        "\n  [bold]Assign AI providers to departments[/bold]\n"
        "  [dim]'auto' = use any available provider (recommended)\n"
        f"  Available: {', '.join(available)}[/dim]\n"
    )

    use_same = Confirm.ask(
        "  Use the same provider for all departments?", default=True
    )

    if use_same:
        idx = _select_option("  Provider for all departments:", provider_list, default=0)
        chosen = provider_map[idx]
        for dept, env_key in _DEPT_ENV_KEYS.items():
            config[env_key] = chosen
        console.print(f"  [green]All departments → {chosen}[/green]")
    else:
        for dept, env_key in _DEPT_ENV_KEYS.items():
            idx = _select_option(
                f"  {_DEPT_LABELS[dept]}:", provider_list, default=0
            )
            chosen = provider_map[idx]
            config[env_key] = chosen
            console.print(f"    [green]{dept} → {chosen}[/green]")


def run_onboarding() -> dict[str, str]:
    """Run the interactive onboarding wizard. Returns a dict of env vars to save."""
    _ensure_utf8()
    config: dict[str, str] = {}

    _play_intro_animation()

    console.print(
        _gradient_panel(
            "[bold]Welcome to Horizon Capital[/bold]\n\n"
            "Let's set up your terminal agent. This wizard will configure\n"
            "your AI providers, broker connections, and trading parameters.\n\n"
            "[dim]This only runs once. You can re-run with: python -m app --setup[/dim]",
            title="Welcome",
        )
    )

    # Step 1: QuickStart vs Advanced
    _step_header(1, 11, "Setup Mode")
    mode_idx = _select_option(
        "How would you like to set up?",
        [
            "QuickStart (Recommended) — sensible defaults, just add API keys",
            "Advanced — configure every parameter",
        ],
        default=0,
    )
    advanced = mode_idx == 1

    # Step 2: LLM Providers
    _step_header(2, 11, "AI Providers")
    console.print("[dim]Which AI providers do you have API keys for?[/dim]")

    # Claude
    if Confirm.ask("  Configure [bold]Anthropic Claude[/bold] (recommended)?", default=True):
        key = _masked_input("Anthropic API key (sk-ant-...)")
        if not key:
            console.print("    [yellow]⚠ No key entered, skipping Claude[/yellow]")
        else:
            verified = asyncio.run(_verify_anthropic_key(key))
            if verified:
                config["ANTHROPIC_API_KEY"] = key
                console.print("    [green]✓ Claude verified[/green]")
            elif Confirm.ask(
                "    [yellow]⚠ Could not verify key. Save anyway?[/yellow]", default=False
            ):
                config["ANTHROPIC_API_KEY"] = key
            else:
                console.print("    [dim]Claude skipped[/dim]")

    # OpenAI
    if Confirm.ask("  Configure [bold]OpenAI[/bold]?", default=False):
        key = _masked_input("OpenAI API key (sk-...)")
        if not key:
            console.print("    [yellow]⚠ No key entered, skipping OpenAI[/yellow]")
        else:
            verified = asyncio.run(_verify_openai_key(key))
            if verified:
                config["OPENAI_API_KEY"] = key
                console.print("    [green]✓ OpenAI verified[/green]")
            elif Confirm.ask(
                "    [yellow]⚠ Could not verify key. Save anyway?[/yellow]", default=False
            ):
                config["OPENAI_API_KEY"] = key
            else:
                console.print("    [dim]OpenAI skipped[/dim]")

    # Gemini
    if Confirm.ask("  Configure [bold]Google Gemini[/bold]?", default=False):
        key = _masked_input("Google API key (AIza...)")
        if not key:
            console.print("    [yellow]⚠ No key entered, skipping Gemini[/yellow]")
        else:
            verified = asyncio.run(_verify_gemini_key(key))
            if verified:
                config["GOOGLE_API_KEY"] = key
                console.print("    [green]✓ Gemini verified[/green]")
            elif Confirm.ask(
                "    [yellow]⚠ Could not verify key. Save anyway?[/yellow]", default=False
            ):
                config["GOOGLE_API_KEY"] = key
            else:
                console.print("    [dim]Gemini skipped[/dim]")

    if not config:
        console.print(
            "\n[yellow]No API keys configured. The system will run with "
            "rule-based strategies only (no AI debates).[/yellow]"
        )

    # Step 3: Broker Setup
    _step_header(3, 11, "Broker Connection")
    broker_idx = _select_option(
        "Connect a broker?",
        [
            "Paper Only (Recommended for first run) — simulated trading",
            "Alpaca (US equities) — connect to Alpaca paper/live API",
            "Zerodha (Indian equities) — connect to Kite API",
        ],
        default=0,
    )

    if broker_idx == 1:
        key = _masked_input("Alpaca API key")
        secret = _masked_input("Alpaca API secret")
        if key and secret:
            config["ALPACA_API_KEY"] = key
            config["ALPACA_API_SECRET"] = secret
            config["ALPACA_PAPER_MODE"] = "true"
            verified = asyncio.run(_verify_alpaca_key(key, secret))
            if verified:
                console.print("    [green]✓ Alpaca connected[/green]")
            else:
                console.print("    [yellow]⚠ Could not verify Alpaca (keys saved)[/yellow]")
    elif broker_idx == 2:
        key = _masked_input("Zerodha API key")
        secret = _masked_input("Zerodha API secret")
        if key:
            config["ZERODHA_API_KEY"] = key
            config["ZERODHA_API_SECRET"] = secret
            config["ZERODHA_MOCK_MODE"] = "true"

    # Steps 4-7: Advanced only
    if advanced:
        # Step 4: Data Providers
        _step_header(4, 11, "Data Providers (Optional)")
        if Confirm.ask("  Configure Polygon.io?", default=False):
            key = _masked_input("Polygon API key")
            if key:
                config["POLYGON_API_KEY"] = key

        if Confirm.ask("  Configure NewsAPI?", default=False):
            key = _masked_input("NewsAPI key")
            if key:
                config["NEWSAPI_API_KEY"] = key

        if Confirm.ask("  Configure Reddit API?", default=False):
            cid = _masked_input("Reddit client ID")
            csecret = _masked_input("Reddit client secret")
            if cid:
                config["REDDIT_CLIENT_ID"] = cid
                config["REDDIT_CLIENT_SECRET"] = csecret

        # Step 5: Trading Universe
        _step_header(5, 11, "Trading Universe")
        console.print("  Default symbols:")
        console.print("    India:  RELIANCE.NSE, TCS.NSE, INFY.NSE, HDFCBANK.NSE, ICICIBANK.NSE")
        console.print(
            "    US:     AAPL.NASDAQ, MSFT.NASDAQ, GOOGL.NASDAQ, AMZN.NASDAQ, TSLA.NASDAQ"
        )
        console.print("    Crypto: BTC-USD, ETH-USD")
        if Confirm.ask("  Customize symbols?", default=False):
            india = Prompt.ask(
                "    India symbols (comma-separated)",
                default="RELIANCE.NSE,TCS.NSE,INFY.NSE,HDFCBANK.NSE,ICICIBANK.NSE",
            )
            us = Prompt.ask(
                "    US symbols (comma-separated)",
                default="AAPL.NASDAQ,MSFT.NASDAQ,GOOGL.NASDAQ,AMZN.NASDAQ,TSLA.NASDAQ",
            )
            crypto = Prompt.ask("    Crypto symbols (comma-separated)", default="BTC-USD,ETH-USD")
            config["INDIA_SYMBOLS"] = india
            config["US_SYMBOLS"] = us
            config["CRYPTO_SYMBOLS"] = crypto

        # Step 6: Risk Parameters
        _step_header(6, 11, "Risk Parameters")
        max_dd = Prompt.ask("  Max drawdown % (kill switch trigger)", default="10")
        max_pos = Prompt.ask("  Max position % per symbol", default="5")
        var_limit = Prompt.ask("  VaR limit %", default="3")
        config["RISK_MAX_DRAWDOWN_PCT"] = max_dd
        config["RISK_MAX_POSITION_PCT"] = max_pos
        config["RISK_VAR_LIMIT_PCT"] = var_limit
    else:
        console.print(
            "\n[dim]Steps 4-7 skipped (using defaults). Re-run with Advanced to customize.[/dim]"
        )

    # Step 7: Initial Capital (Advanced only handled above, but always offer this)
    if advanced:
        _step_header(7, 11, "Initial Capital")
        usd = Prompt.ask("  Starting capital USD", default="1000000")
        inr = Prompt.ask("  Starting capital INR", default="10000000")
        config["INITIAL_CAPITAL_USD"] = usd
        config["INITIAL_CAPITAL_INR"] = inr

    # Step 8: System Mode
    _step_header(8, 11, "System Mode")
    mode_idx = _select_option(
        "Select trading mode:",
        [
            "Paper Trading (Recommended) — simulated orders, no real money",
            "Human Approval — every trade requires your confirmation",
            "Fully Autonomous — system trades automatically within risk limits",
        ],
        default=0,
    )
    mode_map = {0: "PAPER_TRADING", 1: "HUMAN_APPROVAL", 2: "FULLY_AUTONOMOUS"}
    config["SYSTEM_MODE"] = mode_map[mode_idx]

    # Step 9: CIO Mode
    _step_header(9, 11, "CIO Mode")
    cio_idx = _select_option(
        "Who makes the investment decisions?",
        [
            "Human (Recommended) — you act as CIO via interactive terminal",
            "AI — autonomous AI CIO agent governs the system",
        ],
        default=0,
    )
    config["CIO_MODE"] = "HUMAN" if cio_idx == 0 else "AI"

    # Step 10: Department AI Routing
    _step_header(10, 11, "Department AI Routing")
    configured_providers = []
    if config.get("ANTHROPIC_API_KEY"):
        configured_providers.append("claude")
    if config.get("OPENAI_API_KEY"):
        configured_providers.append("openai")
    if config.get("GOOGLE_API_KEY"):
        configured_providers.append("gemini")

    if not configured_providers:
        console.print(
            "  [dim]No AI providers configured — all departments will use rule-based logic.[/dim]"
        )
    else:
        _dept_ai_routing_step(config, configured_providers)

    # Step 11: Health Check & Summary
    _step_header(11, 11, "Health Check")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Verifying configuration...", total=None)
        time.sleep(1)
        progress.update(task, description="Configuration verified ✓")

    # Summary table
    console.print()
    table = Table(
        title="[bold bright_cyan]◆ Configuration Summary ◆[/bold bright_cyan]",
        border_style="bright_cyan",
        show_lines=True,
        padding=(0, 2),
    )
    table.add_column("Setting", style="bold white")
    table.add_column("Value", style="bold green")

    llm_providers = []
    if config.get("ANTHROPIC_API_KEY"):
        llm_providers.append("Claude")
    if config.get("OPENAI_API_KEY"):
        llm_providers.append("OpenAI")
    if config.get("GOOGLE_API_KEY"):
        llm_providers.append("Gemini")

    table.add_row(
        "LLM Providers", ", ".join(llm_providers) if llm_providers else "None (rule-based only)"
    )
    table.add_row("System Mode", config.get("SYSTEM_MODE", "PAPER_TRADING"))
    table.add_row("CIO Mode", config.get("CIO_MODE", "HUMAN"))
    table.add_row("Storage", "LOCAL (SQLite)")

    if config.get("ALPACA_API_KEY"):
        table.add_row("Broker (US)", "Alpaca")
    if config.get("ZERODHA_API_KEY"):
        table.add_row("Broker (India)", "Zerodha")
    if not config.get("ALPACA_API_KEY") and not config.get("ZERODHA_API_KEY"):
        table.add_row("Broker", "Paper Only")

    table.add_row("Max Drawdown", f"{config.get('RISK_MAX_DRAWDOWN_PCT', '10')}%")
    table.add_row("Max Position", f"{config.get('RISK_MAX_POSITION_PCT', '5')}%")

    # AI routing summary
    ai_routing_parts = []
    for dept_short, env_key in [
        ("FrontOff", "AI_FRONT_OFFICE"),
        ("MidOff", "AI_MIDDLE_OFFICE"),
        ("BackOff", "AI_BACK_OFFICE"),
        ("Executive", "AI_EXECUTIVE"),
    ]:
        val = config.get(env_key, "auto")
        ai_routing_parts.append(f"{dept_short}:{val}")
    table.add_row("AI Routing", "  ".join(ai_routing_parts))

    console.print(table)
    console.print()

    if Confirm.ask("[bold]Ready to launch Horizon Capital?[/bold]", default=True):
        _launch_sequence()
        _save_env(config)
        console.print("[green]Configuration saved to .env[/green]\n")

        # Reload settings so API keys are live immediately (not just on next boot)
        try:
            import app.config as _config_mod
            from app.config import Settings as _Settings
            _config_mod.settings = _Settings(_env_file=str(_env_path()))
            from app.llm.provider_registry import provider_registry as _registry
            _registry.auto_register_from_settings()
        except Exception:
            pass  # Non-fatal: keys will be loaded correctly on next boot

        return config
    else:
        console.print("[yellow]Setup cancelled. Run again with: python -m app[/yellow]")
        raise SystemExit(0)


def _save_env(config: dict[str, str]) -> None:
    """Write or merge configuration into the .env file."""
    env_file = _env_path()
    existing: dict[str, str] = {}

    # Load existing .env if present
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    # Merge new config (new values take precedence)
    existing.update(config)

    # Ensure defaults are set
    defaults = {
        "STORAGE_BACKEND": "LOCAL",
        "APP_ENV": "development",
        "APP_DEBUG": "true",
    }
    for k, v in defaults.items():
        if k not in existing:
            existing[k] = v

    # Write back
    lines = [
        "# Horizon Capital Configuration",
        "# Generated by onboarding wizard",
        "",
    ]
    # Group by category
    categories = {
        "System": ["SYSTEM_MODE", "CIO_MODE", "STORAGE_BACKEND", "APP_ENV", "APP_DEBUG"],
        "LLM Providers": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"],
        "Brokers": [
            "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_PAPER_MODE", "ALPACA_BASE_URL",
            "ZERODHA_API_KEY", "ZERODHA_API_SECRET", "ZERODHA_MOCK_MODE",
        ],
        "Data": ["POLYGON_API_KEY", "NEWSAPI_API_KEY", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"],
        "Capital": ["INITIAL_CAPITAL_USD", "INITIAL_CAPITAL_INR"],
        "Risk": [
            "RISK_MAX_DRAWDOWN_PCT", "RISK_MAX_POSITION_PCT",
            "RISK_MAX_LEVERAGE", "RISK_VAR_LIMIT_PCT",
        ],
        "Symbols": ["INDIA_SYMBOLS", "US_SYMBOLS", "CRYPTO_SYMBOLS"],
        "AI Routing": [
            "AI_FRONT_OFFICE", "AI_MIDDLE_OFFICE",
            "AI_BACK_OFFICE", "AI_EXECUTIVE",
        ],
    }

    written_keys: set[str] = set()
    for category, keys in categories.items():
        category_lines = []
        for key in keys:
            if key in existing:
                category_lines.append(f"{key}={existing[key]}")
                written_keys.add(key)
        if category_lines:
            lines.append(f"# {category}")
            lines.extend(category_lines)
            lines.append("")

    # Write any remaining keys
    remaining = {k: v for k, v in existing.items() if k not in written_keys}
    if remaining:
        lines.append("# Other")
        for k, v in remaining.items():
            lines.append(f"{k}={v}")
        lines.append("")

    env_file.write_text("\n".join(lines))
