"""Telegram remote approve/reject worker.

Polls the Telegram Bot API for messages from the configured chat and lets
a human approve or reject orders awaiting approval via ``/approve`` and
``/reject`` commands, without needing the REPL open.
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("services.telegram_approvals")

POLL_INTERVAL = 5.0


class TelegramApprovalWorker:
    """Polls Telegram for /pending, /approve, /reject commands."""

    def __init__(self, orchestrator=None) -> None:
        self._orchestrator = orchestrator
        self._running = False
        self._offset = 0

    async def run(self) -> None:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.info("telegram_approval_worker.disabled")
            return

        self._running = True
        logger.info("telegram_approval_worker.started")
        try:
            while self._running:
                try:
                    await self._poll_once()
                except Exception as exc:
                    logger.warning("telegram_poll_failed", error=str(exc))
                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._running = False

    async def _poll_once(self) -> None:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates",
                    params={
                        "offset": self._offset,
                        "timeout": 0,
                        "allowed_updates": '["message"]',
                    },
                    timeout=10,
                )
                data = resp.json()
        except Exception as exc:
            logger.warning("telegram_get_updates_failed", error=str(exc))
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")

            if str(chat_id) != settings.telegram_chat_id:
                continue

            reply = await self._handle_command(text)
            if reply:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": reply},
                            timeout=10,
                        )
                except Exception as exc:
                    logger.warning("telegram_send_reply_failed", error=str(exc))

    async def _handle_command(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return None
        parts = text.split()
        verb = parts[0].lower()

        if verb == "/pending":
            agent = self._get_execution_agent()
            if agent is None:
                return "Execution agent unavailable."
            orders = agent.get_pending_approvals()
            if not orders:
                return "No pending orders."
            return "\n".join(
                f"{o['id'][:8]} {o['side']} {o['quantity']} {o['symbol']}" for o in orders
            )

        if verb == "/approve":
            if len(parts) < 2:
                return "Usage: /approve <id-prefix>"
            prefix = parts[1]
            agent = self._get_execution_agent()
            if agent is None:
                return "Execution agent unavailable."
            ok = await agent.approve_order(prefix)
            return f"Approved {prefix}." if ok else f"No pending order matching {prefix}."

        if verb == "/reject":
            if len(parts) < 2:
                return "Usage: /reject <id-prefix>"
            prefix = parts[1]
            agent = self._get_execution_agent()
            if agent is None:
                return "Execution agent unavailable."
            ok = await agent.reject_order(prefix)
            return f"Rejected {prefix}." if ok else f"No pending order matching {prefix}."

        return None

    def _get_execution_agent(self):
        if self._orchestrator is None:
            return None
        for slot in self._orchestrator._slots.values():
            if getattr(slot.agent, "agent_type", None) == "execution":
                return slot.agent
        return None
