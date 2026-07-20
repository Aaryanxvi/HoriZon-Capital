"""Trade Journal — plain-language markdown narrative of the day's trading.

Subscribes to fills, kill-switch alerts, and debate conclusions and appends a
one-line, human-readable entry to a daily markdown file. No LLM involved —
template-based narrative only (LLM keys are dead; this must work without them).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.core.messaging import AgentMessage

logger = get_logger("services.trade_journal")

DEFAULT_JOURNAL_DIR = Path.home() / ".horizon-capital" / "journal"


class TradeJournal:
    """Appends a markdown narrative line for each fill, kill switch, and debate result."""

    def __init__(self, bus=None, journal_dir: Path | None = None) -> None:
        if bus is None:
            from app.core.runtime import get_bus
            bus = get_bus()
        self.bus = bus
        self.journal_dir = journal_dir or DEFAULT_JOURNAL_DIR
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to bus events for journaling."""
        self._running = True
        await self.bus.subscribe("horizon.execution.order.fill", self._on_fill)
        await self.bus.subscribe("horizon.risk.alert", self._on_risk_alert)
        await self.bus.subscribe("horizon.debate.*", self._on_debate)
        logger.info("trade_journal.started")

    async def stop(self) -> None:
        self._running = False
        logger.info("trade_journal.stopped")

    # ------------------------------------------------------------------
    # Bus event handlers
    # ------------------------------------------------------------------

    async def _on_fill(self, msg: AgentMessage) -> None:
        try:
            p = msg.payload
            qty = p.get("filled_qty", 0)
            price = p.get("fill_price", 0)
            notional = abs(qty * price)
            broker = p.get("broker")
            via = f" via {broker.upper()}" if broker else ""
            line = (
                f"FILLED {p.get('side', '')} {qty} {p.get('symbol', '')} "
                f"@ ${price:,.2f} — notional ${notional:,.2f}{via}"
            )
            self._append(line)
        except Exception as e:
            logger.warning("trade_journal.write_failed", error=str(e))

    async def _on_risk_alert(self, msg: AgentMessage) -> None:
        try:
            p = msg.payload
            if p.get("action") != "KILL_SWITCH_TRIGGERED":
                return
            drawdown = p.get("current_drawdown", 0)
            limit = p.get("limit", 0)
            line = (
                f"\U0001f6d1 KILL SWITCH: drawdown {drawdown:.2%} breached "
                f"{limit}% limit. All trading halted."
            )
            self._append(line)
        except Exception as e:
            logger.warning("trade_journal.write_failed", error=str(e))

    async def _on_debate(self, msg: AgentMessage) -> None:
        try:
            p = msg.payload
            decision = p.get("decision", "")
            if decision not in ("APPROVED", "REJECTED"):
                return
            reason = p.get("reason")
            suffix = f" — {reason}" if reason else ""
            line = f"Debate {decision} for {p.get('symbol', '')}{suffix}"
            self._append(line)
        except Exception as e:
            logger.warning("trade_journal.write_failed", error=str(e))

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _append(self, entry: str) -> None:
        now = datetime.now(UTC)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        path = self.journal_dir / f"{now:%Y-%m-%d}.md"
        header = f"# Trade Journal — {now:%Y-%m-%d}\n\n" if not path.exists() else ""
        line = f"- **{now:%H:%M:%S}** — {entry}\n"
        # ponytail: sync append, tiny writes; aiofiles if it ever shows in profiles
        with open(path, "a", encoding="utf-8") as f:
            f.write(header + line)
