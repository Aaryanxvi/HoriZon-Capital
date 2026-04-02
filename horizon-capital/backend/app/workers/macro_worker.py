"""MacroFactorWorker -- periodically computes macro regime and publishes to bus.

Fetches real-time term structure from yfinance (^TNX, ^IRX) as a proxy for:
  - Term spread (10Y - 3M)
  - Short rate (Fed funds proxy)
Uses sensible defaults for other Chen-Roll-Ross factors that require FRED data.

Publishes MACRO_REGIME_UPDATE every 30 minutes so strategy agents can subscribe.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger("worker.macro")

# How often to recompute (seconds)
MACRO_INTERVAL = 1800  # 30 minutes


def _fetch_term_spread() -> dict[str, float]:
    """Fetch 10Y and 3-month treasury yields from yfinance.

    Returns a dict with ``short_rate``, ``long_rate``, ``term_spread``.
    Falls back to neutral values on error.
    """
    try:
        import yfinance as yf

        t10y = yf.Ticker("^TNX")
        t3m = yf.Ticker("^IRX")

        hist10 = t10y.history(period="5d")
        hist3m = t3m.history(period="5d")

        long_rate = float(hist10["Close"].iloc[-1]) / 100.0 if not hist10.empty else 0.042
        short_rate = float(hist3m["Close"].iloc[-1]) / 100.0 if not hist3m.empty else 0.052

        return {
            "short_rate": short_rate,
            "long_rate": long_rate,
            "term_spread": long_rate - short_rate,
        }
    except Exception:
        return {"short_rate": 0.052, "long_rate": 0.042, "term_spread": -0.010}


def _build_macro_data(term: dict[str, float]) -> dict[str, float]:
    """Build a macro factor dict using real term structure + reasonable defaults.

    Factors without live feeds use a neutral baseline (0.0) so they don't
    artificially skew the composite score.
    """
    return {
        "industrial_production": 0.0,    # Neutral: no live FRED feed
        "inflation_surprise": 0.0,       # Neutral: no CPI expectation feed
        "credit_spread": 0.012,          # IG credit spread approx ~1.2%
        "term_spread": term["term_spread"],
        "fed_rate": term["short_rate"],
        "unemployment": 0.0,             # Neutral: no live BLS feed
        "consumer_confidence": 0.0,      # Neutral: no live feed
    }


class MacroFactorWorker:
    """Runs macro factor analysis on a schedule and publishes to the agent bus."""

    def __init__(self, bus: Any = None) -> None:
        self._bus = bus
        self._running = False

    def set_bus(self, bus: Any) -> None:
        self._bus = bus

    async def run(self) -> None:
        self._running = True
        logger.info("macro_worker.starting")

        # Run once immediately at startup
        await self._compute_and_publish()

        try:
            while self._running:
                await asyncio.sleep(MACRO_INTERVAL)
                await self._compute_and_publish()
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        logger.info("macro_worker.stopping")
        self._running = False

    async def _compute_and_publish(self) -> None:
        if not self._bus:
            logger.warning("macro_worker.no_bus_skipping")
            return

        try:
            from app.services.macro_factors import MacroIntegrationService

            term = await asyncio.get_event_loop().run_in_executor(None, _fetch_term_spread)
            macro_data = _build_macro_data(term)

            service = MacroIntegrationService()
            result = service.analyze(
                macro_data=macro_data,
                term_structure={
                    "short_rate": term["short_rate"],
                    "long_rate": term["long_rate"],
                    "credit_spread": macro_data["credit_spread"],
                },
            )

            await self._bus.publish(
                AgentMessage(
                    sender_id="macro-worker",
                    channel="horizon.macro.regime",
                    message_type=MessageType.MACRO_REGIME_UPDATE,
                    payload={
                        "macro_regime": result["macro_regime"],
                        "composite_score": result["composite_score"],
                        "risk_adjustment": result["risk_adjustment"],
                        "term_spread": term["term_spread"],
                        "short_rate": term["short_rate"],
                        "long_rate": term["long_rate"],
                        "term_structure": result.get("term_structure", {}),
                        "factor_contributions": result.get("factor_contributions", {}),
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            )

            logger.info(
                "macro_worker.published",
                regime=result["macro_regime"],
                composite=result["composite_score"],
                risk_adj=result["risk_adjustment"],
                term_spread=f"{term['term_spread']*100:.2f}bps",
            )
        except Exception as exc:
            logger.error("macro_worker.error", error=str(exc))
