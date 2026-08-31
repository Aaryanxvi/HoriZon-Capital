"""Trade Journal — plain-language markdown narrative of the day's trading.

Subscribes to fills, kill-switch alerts, and debate conclusions and appends a
one-line, human-readable entry to a daily markdown file. No LLM involved —
template-based narrative only (LLM keys are dead; this must work without them).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.messaging import AgentMessage

logger = get_logger("services.trade_journal")

DEFAULT_JOURNAL_DIR = Path.home() / ".horizon-capital" / "journal"

_EMPTY_CHAIN = {
    "strategy": None,
    "regime": None,
    "strength": None,
    "signal_reasoning": None,
    "debate_decision": None,
    "debate_score": None,
    "debate_reason": None,
}


def _compose_why(chain: dict) -> str | None:
    parts = []
    if chain.get("strategy") is not None:
        parts.append(f"strategy {chain['strategy']}")
    if chain.get("regime") is not None:
        parts.append(f"regime {chain['regime']}")
    if chain.get("strength") is not None:
        parts.append(f"strength {chain['strength']:.2f}")
    if chain.get("signal_reasoning") is not None:
        parts.append(str(chain["signal_reasoning"])[:120])
    if chain.get("debate_decision") is not None:
        score = chain.get("debate_score")
        score_str = f"{score:.2f}" if score is not None else "n/a"
        parts.append(f"debate {chain['debate_decision']} ({score_str})")
    if chain.get("debate_reason") is not None:
        parts.append(f'"{str(chain["debate_reason"])[:120]}"')
    if not parts:
        return None
    return "; ".join(parts)


async def resolve_decision_chain(order_id: str) -> dict:
    """Resolve the signal/debate provenance for a filled order.

    Never raises; returns a dict of all-None values on any failure.
    """
    chain = dict(_EMPTY_CHAIN)
    try:
        from app.core.runtime import get_session_factory

        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT signal_id, debate_id, symbol FROM orders WHERE id = :oid"),
                {"oid": order_id},
            )
            order_row = result.mappings().first()
            if order_row is None:
                return chain

            signal_id = order_row.get("signal_id")
            debate_id = order_row.get("debate_id")
            symbol = order_row.get("symbol")

            if signal_id:
                sig_result = await session.execute(
                    text(
                        "SELECT strategy_name, regime, strength, metadata "
                        "FROM signals WHERE signal_id = :sid"
                    ),
                    {"sid": signal_id},
                )
                sig_row = sig_result.mappings().first()
                if sig_row is not None:
                    chain["strategy"] = sig_row.get("strategy_name")
                    chain["regime"] = sig_row.get("regime")
                    chain["strength"] = sig_row.get("strength")
                    metadata_raw = sig_row.get("metadata")
                    if metadata_raw:
                        try:
                            metadata = json.loads(metadata_raw)
                            reasoning = metadata.get("reasoning") or metadata.get("reason")
                            if reasoning:
                                chain["signal_reasoning"] = reasoning
                        except (TypeError, ValueError):
                            pass

            debate_row = None
            if debate_id:
                deb_result = await session.execute(
                    text(
                        "SELECT final_decision, consensus_score, reason "
                        "FROM debate_sessions WHERE id = :did"
                    ),
                    {"did": debate_id},
                )
                debate_row = deb_result.mappings().first()
            elif symbol:
                cutoff = datetime.now(UTC) - timedelta(minutes=15)
                deb_result = await session.execute(
                    text(
                        "SELECT final_decision, consensus_score, reason "
                        "FROM debate_sessions WHERE symbol = :sym AND created_at >= :cutoff "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"sym": symbol, "cutoff": cutoff},
                )
                debate_row = deb_result.mappings().first()

            if debate_row is not None:
                chain["debate_decision"] = debate_row.get("final_decision")
                chain["debate_score"] = debate_row.get("consensus_score")
                chain["debate_reason"] = debate_row.get("reason") or None

            return chain
    except Exception:
        return dict(_EMPTY_CHAIN)


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
            from app.config import settings

            if settings.journal_decision_chain:
                chain = await resolve_decision_chain(p.get("order_id", ""))
                why = _compose_why(chain)
                if why:
                    line = f"{line}\n    - why: {why}"
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
