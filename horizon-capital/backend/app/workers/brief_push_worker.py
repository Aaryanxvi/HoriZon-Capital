# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-518925B6CD6A
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""BriefPushWorker -- pushes the morning brief to Telegram once per day.

Every CHECK_INTERVAL seconds, checks whether it's past pre-market open
(FIRE_AFTER_UTC) on a weekday and the brief hasn't already been pushed
today (deduped via a KV marker). Sends the brief as a plain-text
Telegram message if Telegram is configured.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from app.config import settings
from app.core.kv_store import get_kv_store
from app.core.logging import get_logger

logger = get_logger("worker.brief_push")

CHECK_INTERVAL = 300.0
FIRE_AFTER_UTC = "12:30"
LAST_RUN_KEY = "horizon:brief:push:last_date"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_plain(text: str) -> str:
    try:
        from rich.text import Text

        plain = Text.from_markup(text).plain
    except Exception:
        plain = re.sub(r"\[/?[a-zA-Z][^\]]*\]", "", text)

    if len(plain) > 4000:
        plain = plain[:4000] + "\n… (truncated)"
    return plain


class BriefPushWorker:
    """Pushes the morning brief to Telegram once per trading day."""

    def __init__(self, orchestrator=None) -> None:
        self._orchestrator = orchestrator
        self._running = False

    async def run(self) -> None:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.info("brief_push_worker.disabled")
            return

        self._running = True
        logger.info("brief_push_worker.started")
        try:
            while self._running:
                try:
                    await self._maybe_fire()
                except Exception as exc:
                    logger.error("brief_push_worker_error", error=str(exc))
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

        await self._push_brief()
        await kv.set(LAST_RUN_KEY, today_str)

    async def _push_brief(self) -> None:
        try:
            from app.services.morning_brief import build_morning_brief

            brief = await build_morning_brief(orchestrator=self._orchestrator)
            plain = _to_plain(brief)

            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": settings.telegram_chat_id, "text": plain},
                    timeout=10,
                )

            logger.info("morning_brief_pushed", chars=len(plain))
        except Exception as exc:
            logger.warning("morning_brief_push_failed", error=str(exc))
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 518925B6CD6A - verify with scripts/authorship.py verify
