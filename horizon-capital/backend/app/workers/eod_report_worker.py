"""EODReportWorker -- generates and emails the end-of-day markdown report.

Every CHECK_INTERVAL seconds, checks whether it's past US market close
(FIRE_AFTER_UTC) on a weekday and the EOD report hasn't already been
generated today (deduped via a KV marker). Saves the report to
``~/.horizon-capital/reports/eod_{date}.md`` and emails it if SMTP is
configured.
"""

from __future__ import annotations

import asyncio
import json
import smtplib
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger

logger = get_logger("worker.eod_report")

CHECK_INTERVAL = 300.0
FIRE_AFTER_UTC = "21:05"
LAST_RUN_KEY = "horizon:report:eod:last_date"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EODReportWorker:
    """Generates the end-of-day portfolio report and (optionally) emails it."""

    def __init__(self, orchestrator=None) -> None:
        self._orchestrator = orchestrator
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("eod_report_worker.started")
        try:
            while self._running:
                try:
                    await self._maybe_fire()
                except Exception as exc:
                    logger.error("eod_report_worker_error", error=str(exc))
                await asyncio.sleep(CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False

    async def _maybe_fire(self) -> None:
        now = _utcnow()
        if now.weekday() >= 5:
            return

        if now.strftime("%H:%M") < FIRE_AFTER_UTC:
            return

        today_str = now.strftime("%Y-%m-%d")
        kv = get_kv_store()
        last_run = await kv.get(LAST_RUN_KEY)
        if last_run == today_str:
            return

        await self._generate_and_send()
        await kv.set(LAST_RUN_KEY, today_str)

    async def _generate_and_send(self) -> None:
        try:
            from app.services.report_generator import ReportGenerator

            generator = ReportGenerator()
            report = await generator.generate("daily")
            md = generator.to_markdown(report)

            md += "\n## Sleeve Attribution\n"
            md += await self._render_attribution()

            md += "\n\n## Alpha Decay\n"
            md += self._render_alpha_decay()
            md += "\n"

            today_str = _utcnow().strftime("%Y-%m-%d")
            reports_dir = Path.home() / ".horizon-capital" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            filepath = reports_dir / f"eod_{today_str}.md"
            filepath.write_text(md, encoding="utf-8")

            if settings.alert_email_smtp_host and settings.alert_email_to:
                await self._send_email(today_str, md)

            logger.info("eod_report_generated", path=str(filepath))
        except Exception as exc:
            logger.error("eod_report_generation_failed", error=str(exc))

    async def _render_attribution(self) -> str:
        try:
            from sqlalchemy import text

            from app.core.runtime import get_session_factory

            async with get_session_factory()() as session:
                row = await session.execute(
                    text("""
                        SELECT attribution
                        FROM performance_snapshots
                        WHERE period = '1d'
                        ORDER BY created_at DESC LIMIT 1
                    """)
                )
                data = row.fetchone()

            if not data or not data[0]:
                return "_No attribution data._"

            attribution = json.loads(data[0])
            if not isinstance(attribution, dict) or not attribution:
                return "_No attribution data._"

            lines = ["| Strategy | value |", "|---|---|"]
            for strategy, value in attribution.items():
                lines.append(f"| {strategy} | {value} |")
            return "\n".join(lines)
        except Exception:
            return "_No attribution data._"

    def _render_alpha_decay(self) -> str:
        if self._orchestrator is None:
            return "_No alpha-decay warnings._"

        agent = None
        try:
            for slot in self._orchestrator._slots.values():
                if getattr(slot.agent, "agent_id", None) == "alpha-monitor-1":
                    agent = slot.agent
                    break
        except Exception:
            return "_No alpha-decay warnings._"

        if agent is None:
            return "_No alpha-decay warnings._"

        try:
            metrics = agent.get_strategy_metrics()
        except Exception:
            return "_No alpha-decay warnings._"

        warnings = []
        for strategy, m in metrics.items():
            total_trades = m.get("total_trades", 0)
            sharpe = m.get("sharpe", 0.0)
            win_rate = m.get("win_rate", 0.0)
            if total_trades >= 20 and (sharpe < 0.5 or win_rate < 0.5):
                warnings.append(
                    f"- ⚠ {strategy}: sharpe {sharpe:.2f}, "
                    f"win rate {win_rate:.0%}, trades {total_trades}"
                )

        if not warnings:
            return "_No alpha-decay warnings._"
        return "\n".join(warnings)

    async def _send_email(self, date_str: str, body: str) -> None:
        try:
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = f"[Horizon Capital] EOD Report {date_str}"
            msg["From"] = settings.alert_email_from
            msg["To"] = settings.alert_email_to

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._send_email_sync(msg))
        except Exception as exc:
            logger.warning("eod_report_email_failed", error=str(exc))

    @staticmethod
    def _send_email_sync(msg) -> None:  # noqa: ANN001
        with smtplib.SMTP(
            settings.alert_email_smtp_host,
            settings.alert_email_smtp_port,
        ) as server:
            server.starttls()
            if settings.alert_email_password:
                server.login(settings.alert_email_from, settings.alert_email_password)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())
