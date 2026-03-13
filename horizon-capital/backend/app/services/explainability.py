"""Per-trade explainability service.

Pulls data from signals, debate_arguments, risk_metrics, and sentiment_aggregates
to produce a human-readable attribution for every executed order.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.logging import get_logger

logger = get_logger("services.explainability")


class ExplainabilityService:
    """Generate per-trade explanations by combining all decision inputs."""

    @staticmethod
    async def explain_trade(order_id: str | uuid.UUID) -> dict:
        """Build a full attribution breakdown for a given order.

        Parameters
        ----------
        order_id : str | UUID
            The ``orders.id`` to explain.

        Returns
        -------
        dict
            {
                "order_id": str,
                "symbol": str,
                "side": str,
                "strategy_contribution_pct": float,
                "sentiment_influence_pct": float,
                "regime_context": str,
                "debate_summary": dict,
                "risk_assessment": dict,
            }
        """
        oid = str(order_id)

        async with async_session_factory() as session:
            # 1. Fetch the order itself
            order_row = await session.execute(
                text(
                    """
                    SELECT id, symbol, side, signal_id, debate_id, status, created_at
                    FROM orders
                    WHERE id = :oid
                    """
                ),
                {"oid": oid},
            )
            order = order_row.fetchone()
            if order is None:
                logger.warning("explain_trade_order_not_found", order_id=oid)
                return {"order_id": oid, "error": "Order not found"}

            symbol = order[1]
            side = order[2]
            signal_id = str(order[3]) if order[3] else None
            debate_id = str(order[4]) if order[4] else None

            # 2. Fetch the originating signal
            signal_data: dict = {}
            if signal_id:
                sig_row = await session.execute(
                    text(
                        """
                        SELECT strategy_name, strength, direction, reasoning,
                               regime_at_signal
                        FROM signals
                        WHERE id = :sid
                        """
                    ),
                    {"sid": signal_id},
                )
                sig = sig_row.fetchone()
                if sig:
                    signal_data = {
                        "strategy_name": sig[0],
                        "strength": float(sig[1]),
                        "direction": int(sig[2]),
                        "reasoning": sig[3],
                        "regime_at_signal": sig[4],
                    }

            # 3. Fetch debate arguments
            debate_summary: dict = {"decision": None, "arguments": [], "consensus_score": None}
            if debate_id:
                debate_row = await session.execute(
                    text(
                        """
                        SELECT final_decision, consensus_score, total_rounds
                        FROM debate_sessions
                        WHERE id = :did
                        """
                    ),
                    {"did": debate_id},
                )
                debate = debate_row.fetchone()
                if debate:
                    debate_summary["decision"] = debate[0]
                    debate_summary["consensus_score"] = float(debate[1]) if debate[1] else None
                    debate_summary["total_rounds"] = int(debate[2])

                args_rows = await session.execute(
                    text(
                        """
                        SELECT agent_id, role, vote, confidence, argument, round_number
                        FROM debate_arguments
                        WHERE session_id = :did
                        ORDER BY round_number, created_at
                        """
                    ),
                    {"did": debate_id},
                )
                for row in args_rows.fetchall():
                    debate_summary["arguments"].append({
                        "agent_id": row[0],
                        "role": row[1],
                        "vote": row[2],
                        "confidence": float(row[3]),
                        "argument": row[4],
                        "round": int(row[5]),
                    })

            # 4. Latest risk metrics snapshot
            risk_row = await session.execute(
                text(
                    """
                    SELECT var_1d_95, cvar_1d_95, max_drawdown, current_drawdown,
                           kill_switch_active
                    FROM risk_metrics
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
            )
            risk = risk_row.fetchone()
            risk_assessment: dict = {}
            if risk:
                risk_assessment = {
                    "var_1d_95": float(risk[0]),
                    "cvar_1d_95": float(risk[1]),
                    "max_drawdown": float(risk[2]),
                    "current_drawdown": float(risk[3]),
                    "kill_switch_active": bool(risk[4]),
                }

            # 5. Latest sentiment aggregate for this symbol
            sent_row = await session.execute(
                text(
                    """
                    SELECT avg_sentiment, bull_pct, bear_pct, article_count
                    FROM sentiment_aggregates
                    WHERE symbol = :symbol
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"symbol": symbol},
            )
            sent = sent_row.fetchone()

            # 6. Compute contribution percentages
            strategy_pct = signal_data.get("strength", 0.5) * 100
            sentiment_influence = 0.0
            if sent:
                # Sentiment influence: deviation from neutral scaled to 0-30 %
                sentiment_influence = abs(float(sent[0])) * 30.0

            # Normalize so strategy + sentiment + debate confidence = ~100 %
            debate_conf = debate_summary.get("consensus_score") or 0.0
            debate_contrib = debate_conf * 20.0  # max 20 %

            total_raw = strategy_pct + sentiment_influence + debate_contrib
            if total_raw > 0:
                strategy_contribution_pct = round(strategy_pct / total_raw * 100, 1)
                sentiment_influence_pct = round(sentiment_influence / total_raw * 100, 1)
            else:
                strategy_contribution_pct = 100.0
                sentiment_influence_pct = 0.0

            regime_context = signal_data.get("regime_at_signal", "UNKNOWN")

        explanation = {
            "order_id": oid,
            "symbol": symbol,
            "side": side,
            "strategy_contribution_pct": strategy_contribution_pct,
            "sentiment_influence_pct": sentiment_influence_pct,
            "regime_context": regime_context,
            "debate_summary": debate_summary,
            "risk_assessment": risk_assessment,
            "signal_detail": signal_data,
        }

        logger.info("trade_explained", order_id=oid, symbol=symbol)
        return explanation
