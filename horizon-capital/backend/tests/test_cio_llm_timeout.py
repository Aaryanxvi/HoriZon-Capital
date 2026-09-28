# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-0BC22F778CA8
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""CIO LLM calls time out and trip circuit breaker."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_mode_a_times_out_hung_llm():
    from app.agents.executive.cio.cio_agent import CIOAgent

    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    agent = CIOAgent(bus=bus)
    agent._running = True

    async def hang(*a, **kw):
        await asyncio.sleep(10)

    provider = MagicMock()
    provider.provider_name = "claude"
    provider.complete = AsyncMock(side_effect=hang)

    with patch("app.agents.executive.cio.cio_agent.provider_registry") as reg, \
         patch("app.agents.executive.cio.cio_agent.CIO_LLM_TIMEOUT_S", 0.05):
        reg.get_providers_for_department.return_value = [provider]
        reg.get_provider_for_agent.return_value = provider

        await agent._run_mode_a()

    assert agent._llm_failures == 1
    bus.publish.assert_not_awaited()
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token 0BC22F778CA8 - verify with scripts/authorship.py verify
