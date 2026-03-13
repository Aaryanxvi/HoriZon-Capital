"""Alerting service: Telegram, Email, and unified routing.

Sends alerts through configured channels based on severity.  Configuration
is read from ``app.config.settings``.
"""

from __future__ import annotations

import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("monitoring.alerting")


class AlertService:
    """Multi-channel alerting for Horizon Capital operations."""

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    @staticmethod
    async def send_telegram(message: str) -> bool:
        """Send a message via the Telegram Bot API.

        Requires ``settings.telegram_bot_token`` and ``settings.telegram_chat_id``
        to be configured.

        Returns
        -------
        bool
            ``True`` if the message was sent successfully.
        """
        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id

        if not token or not chat_id:
            logger.warning("telegram_not_configured")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            logger.info("telegram_sent", chat_id=chat_id, length=len(message))
            return True
        except httpx.HTTPError as exc:
            logger.error("telegram_send_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Email (SMTP)
    # ------------------------------------------------------------------

    @staticmethod
    async def send_email(subject: str, body: str) -> bool:
        """Send an email alert via SMTP.

        Uses ``settings.alert_email_*`` configuration.  Falls back to stdlib
        ``smtplib`` (synchronous, wrapped for compatibility).

        Returns
        -------
        bool
            ``True`` if the email was sent successfully.
        """
        smtp_host = settings.alert_email_smtp_host
        smtp_port = settings.alert_email_smtp_port
        from_addr = settings.alert_email_from
        to_addr = settings.alert_email_to
        password = settings.alert_email_password

        if not smtp_host or not from_addr or not to_addr:
            logger.warning("email_not_configured")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[Horizon Capital] {subject}"
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(f"<pre>{body}</pre>", "html"))

        try:
            # Use aiosmtplib if available, otherwise fall back to sync smtplib
            try:
                import aiosmtplib

                await aiosmtplib.send(
                    msg,
                    hostname=smtp_host,
                    port=smtp_port,
                    username=from_addr,
                    password=password,
                    start_tls=True,
                )
            except ImportError:
                # Synchronous fallback
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    if password:
                        server.login(from_addr, password)
                    server.sendmail(from_addr, [to_addr], msg.as_string())

            logger.info("email_sent", to=to_addr, subject=subject)
            return True
        except Exception as exc:
            logger.error("email_send_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Unified alert router
    # ------------------------------------------------------------------

    @staticmethod
    async def alert(message: str, severity: str = "WARNING") -> dict:
        """Route an alert to all configured channels.

        Severity levels
        ---------------
        - ``INFO``     -- logged only
        - ``WARNING``  -- Telegram
        - ``CRITICAL`` -- Telegram + Email

        Parameters
        ----------
        message : str
            Human-readable alert message.
        severity : str
            One of ``INFO``, ``WARNING``, ``CRITICAL``.

        Returns
        -------
        dict
            ``{severity, telegram_sent, email_sent, timestamp}``.
        """
        severity = severity.upper()
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted = (
            f"<b>[{severity}]</b> Horizon Capital\n"
            f"<code>{timestamp}</code>\n\n"
            f"{message}"
        )

        telegram_sent = False
        email_sent = False

        if severity in ("WARNING", "CRITICAL"):
            telegram_sent = await AlertService.send_telegram(formatted)

        if severity == "CRITICAL":
            email_sent = await AlertService.send_email(
                subject=f"{severity}: {message[:80]}",
                body=f"Severity: {severity}\nTime: {timestamp}\n\n{message}",
            )

        logger.info(
            "alert_dispatched",
            severity=severity,
            telegram=telegram_sent,
            email=email_sent,
        )

        return {
            "severity": severity,
            "telegram_sent": telegram_sent,
            "email_sent": email_sent,
            "timestamp": timestamp,
        }
