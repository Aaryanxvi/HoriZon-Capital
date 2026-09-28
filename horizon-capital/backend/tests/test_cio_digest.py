# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-411BE0BCF3C9
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""Test CIO portfolio digest reads the correct KV keys."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_digest_reads_horizon_portfolio_nav():
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    kv = MagicMock()
    kv.get = AsyncMock(side_effect=lambda k: {
        "horizon:portfolio:nav": "1234567",
    }.get(k))

    sess_ctx = AsyncMock()
    sess_ctx.__aenter__ = AsyncMock(return_value=sess_ctx)
    sess_ctx.__aexit__ = AsyncMock(return_value=None)
    sess_result = MagicMock()
    sess_result.scalar = MagicMock(return_value=3)
    sess_ctx.execute = AsyncMock(return_value=sess_result)
    factory = MagicMock(return_value=sess_ctx)

    with patch("app.agents.executive.cio.cio_agent._get_session_factory",
               return_value=factory), \
         patch("app.core.kv_store.get_kv_store", return_value=kv):
        digest = await agent._build_portfolio_digest()

    assert digest["nav"] == "1234567"
    assert digest["open_positions"] == 3


@pytest.mark.asyncio
async def test_digest_omits_missing_keys_gracefully():
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)

    kv = MagicMock()
    kv.get = AsyncMock(return_value=None)

    sess_ctx = AsyncMock()
    sess_ctx.__aenter__ = AsyncMock(return_value=sess_ctx)
    sess_ctx.__aexit__ = AsyncMock(return_value=None)
    sess_result = MagicMock()
    sess_result.scalar = MagicMock(return_value=0)
    sess_ctx.execute = AsyncMock(return_value=sess_result)
    factory = MagicMock(return_value=sess_ctx)

    with patch("app.agents.executive.cio.cio_agent._get_session_factory",
               return_value=factory), \
         patch("app.core.kv_store.get_kv_store", return_value=kv):
        digest = await agent._build_portfolio_digest()

    assert "nav" not in digest
    assert digest["open_positions"] == 0
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 411BE0BCF3C9 - verify with scripts/authorship.py verify
