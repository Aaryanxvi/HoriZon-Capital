# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-28DC1F3683E3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Trade journal with full explainability.

Records every trade with comprehensive context: why the trade was made,
what signals fired, what market regime was active, what the debate concluded,
and what the actual outcome was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.core.logging import get_logger

logger = get_logger("backtesting.trade_journal")


@dataclass
class JournalEntry:
    """A single trade journal entry with full explainability."""

    # Trade identification
    trade_id: str = ""
    symbol: str = ""
    side: str = ""  # BUY / SELL
    quantity: float = 0.0
    price: float = 0.0
    timestamp: str = ""

    # Outcome
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_period_bars: int = 0
    commission: float = 0.0
    slippage: float = 0.0

    # Context — WHY the trade was made
    strategy_name: str = ""
    signal_strength: float = 0.0
    signal_direction: str = ""  # BUY / SELL / HOLD

    # Regime context
    regime: str = ""
    regime_confidence: float = 0.0

    # Sentiment context
    sentiment_score: float = 0.0
    sentiment_source: str = ""

    # Debate context
    debate_result: str = ""  # APPROVED / REJECTED
    debate_for: int = 0
    debate_against: int = 0
    debate_consensus: float = 0.0

    # Risk context
    portfolio_value_at_entry: float = 0.0
    position_size_pct: float = 0.0
    var_at_entry: float = 0.0

    # Tags for filtering
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for k in self.__dataclass_fields__:
            result[k] = getattr(self, k)
        return result


class TradeJournal:
    """Trade journal that aggregates per-trade explainability data.

    Combines trade execution data with attribution engine context to
    produce a complete audit trail for every trade.
    """

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    @property
    def entries(self) -> list[JournalEntry]:
        return list(self._entries)

    def add_entry(self, entry: JournalEntry) -> None:
        """Add a journal entry."""
        self._entries.append(entry)
        logger.debug("journal_entry_added", symbol=entry.symbol, side=entry.side)

    def record_trade(
        self,
        trade: dict[str, Any],
        attribution: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Record a trade with optional attribution and context.

        Parameters
        ----------
        trade:
            Trade dict with at least: symbol, side, quantity, price, pnl.
        attribution:
            Attribution engine output (strategy_alpha, sentiment_alpha, etc.)
        context:
            Additional context: regime, portfolio_value, var, etc.
        """
        attr = attribution or {}
        ctx = context or {}

        entry = JournalEntry(
            trade_id=trade.get("trade_id", trade.get("order_id", "")),
            symbol=trade.get("symbol", ""),
            side=trade.get("side", ""),
            quantity=trade.get("quantity", 0.0),
            price=trade.get("price", trade.get("fill_price", 0.0)),
            timestamp=str(trade.get("timestamp", datetime.now(UTC).isoformat())),
            pnl=trade.get("pnl", 0.0),
            pnl_pct=trade.get("pnl_pct", 0.0),
            holding_period_bars=trade.get("holding_period_bars", 0),
            commission=trade.get("commission", 0.0),
            slippage=trade.get("slippage", 0.0),
            # Attribution
            strategy_name=attr.get("strategy_name", ctx.get("strategy_name", "")),
            signal_strength=attr.get("strategy_alpha", 0.0),
            signal_direction=attr.get("signal_direction", trade.get("side", "")),
            # Regime
            regime=attr.get("regime", ctx.get("regime", "")),
            regime_confidence=attr.get("regime_confidence", 0.0),
            # Sentiment
            sentiment_score=attr.get("sentiment_alpha", 0.0),
            sentiment_source=ctx.get("sentiment_source", ""),
            # Debate
            debate_result=ctx.get("debate_result", ""),
            debate_for=attr.get("debate_for", 0),
            debate_against=attr.get("debate_against", 0),
            debate_consensus=attr.get("debate_consensus_score", 0.0),
            # Risk
            portfolio_value_at_entry=ctx.get("portfolio_value", 0.0),
            position_size_pct=ctx.get("position_size_pct", 0.0),
            var_at_entry=ctx.get("var", 0.0),
        )

        self._entries.append(entry)
        return entry

    # ------------------------------------------------------------------
    # Query / filter
    # ------------------------------------------------------------------

    def filter(
        self,
        symbol: str | None = None,
        side: str | None = None,
        strategy: str | None = None,
        regime: str | None = None,
        min_pnl: float | None = None,
        max_pnl: float | None = None,
    ) -> list[JournalEntry]:
        """Filter journal entries by criteria."""
        results = self._entries
        if symbol:
            results = [e for e in results if e.symbol == symbol]
        if side:
            results = [e for e in results if e.side == side]
        if strategy:
            results = [e for e in results if e.strategy_name == strategy]
        if regime:
            results = [e for e in results if e.regime == regime]
        if min_pnl is not None:
            results = [e for e in results if e.pnl >= min_pnl]
        if max_pnl is not None:
            results = [e for e in results if e.pnl <= max_pnl]
        return results

    def summary(self) -> dict[str, Any]:
        """Compute journal-level summary statistics."""
        if not self._entries:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "by_strategy": {},
                "by_regime": {},
            }

        pnls = [e.pnl for e in self._entries]
        by_strategy: dict[str, dict] = {}
        by_regime: dict[str, dict] = {}

        for entry in self._entries:
            # By strategy
            s = entry.strategy_name or "unknown"
            if s not in by_strategy:
                by_strategy[s] = {"count": 0, "pnl": 0.0, "wins": 0}
            by_strategy[s]["count"] += 1
            by_strategy[s]["pnl"] += entry.pnl
            if entry.pnl > 0:
                by_strategy[s]["wins"] += 1

            # By regime
            r = entry.regime or "UNKNOWN"
            if r not in by_regime:
                by_regime[r] = {"count": 0, "pnl": 0.0, "wins": 0}
            by_regime[r]["count"] += 1
            by_regime[r]["pnl"] += entry.pnl
            if entry.pnl > 0:
                by_regime[r]["wins"] += 1

        # Win rates
        for group in [by_strategy, by_regime]:
            for v in group.values():
                v["win_rate"] = round(v["wins"] / v["count"], 4) if v["count"] > 0 else 0.0
                v["pnl"] = round(v["pnl"], 4)

        return {
            "total_trades": len(self._entries),
            "winning_trades": sum(1 for p in pnls if p > 0),
            "losing_trades": sum(1 for p in pnls if p < 0),
            "total_pnl": round(sum(pnls), 4),
            "avg_pnl": round(float(np.mean(pnls)), 4),
            "best_trade": round(max(pnls), 4),
            "worst_trade": round(min(pnls), 4),
            "by_strategy": by_strategy,
            "by_regime": by_regime,
        }

    def to_list(self) -> list[dict[str, Any]]:
        """Export all entries as list of dicts."""
        return [e.to_dict() for e in self._entries]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 28DC1F3683E3 - verify with scripts/authorship.py verify
