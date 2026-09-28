# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-B1D879E9AA69
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Regression test for agent_messages retention pruning (ITAgent).

agent_messages has no cleanup elsewhere — every bus publish inserts a row
via BaseAgent.emit — so ITAgent._prune_agent_messages must delete rows
older than settings.agent_messages_retention_days.
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy import text

from app.agents.back_office.it.it_agent import ITAgent


async def test_prune_agent_messages_deletes_only_stale_rows():
    from app.core.local_storage import init_local_db
    from app.core.runtime import get_session_factory

    await init_local_db()

    agent = ITAgent(bus=MagicMock())

    old_ts = datetime.now(UTC) - timedelta(days=30)
    fresh_ts = datetime.now(UTC)

    async with get_session_factory()() as session:
        await session.execute(
            text(
                """
                INSERT INTO agent_messages
                    (message_id, sender_id, channel, message_type, payload, created_at)
                VALUES
                    (:message_id, 'test-agent', 'horizon.test', 'HEARTBEAT', '{}', :created_at)
                """
            ),
            [
                {"message_id": "old-msg", "created_at": old_ts},
                {"message_id": "fresh-msg", "created_at": fresh_ts},
            ],
        )
        await session.commit()

    await agent._prune_agent_messages()

    async with get_session_factory()() as session:
        result = await session.execute(text("SELECT message_id FROM agent_messages"))
        remaining = {row.message_id for row in result.fetchall()}

    assert remaining == {"fresh-msg"}
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token B1D879E9AA69 - verify with scripts/authorship.py verify
