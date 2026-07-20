"""Guards against the halt-key split regressing: REST halt/kill-switch endpoints
must write the same key (`horizon:system:halted`, "1"/"0") that the live trading
agents (risk_agent, execution_agent, portfolio_agent, health_monitor) read.
"""

import pytest

from app.api.v1 import cio, risk


class FakeResult:
    def scalar_one_or_none(self):
        return None


class FakeDB:
    """Minimal stand-in for AsyncSession — no risk metric row to update."""

    async def execute(self, _stmt):
        return FakeResult()

    async def flush(self):
        pass


class FakeRedis:
    """Minimal in-memory stand-in for the module-level redis_client."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def setex(self, key, _ttl, value):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def publish(self, _channel, _payload):
        pass


@pytest.mark.asyncio
async def test_cio_halt_sets_canonical_key(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cio, "redis_client", fake)

    await cio.halt_system(cio.HaltRequest(reason="test"), _user={})

    assert fake.store["horizon:system:halted"] == "1"
    assert "horizon:system:halt_active" not in fake.store
    assert "horizon:risk:kill_switch" not in fake.store


@pytest.mark.asyncio
async def test_risk_kill_switch_activate_deactivate_use_canonical_key(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(risk, "redis_client", fake)

    fake_db = FakeDB()
    await risk.activate_kill_switch(db=fake_db, _user={})
    assert fake.store["horizon:system:halted"] == "1"

    await risk.deactivate_kill_switch(db=fake_db, _user={})
    assert fake.store["horizon:system:halted"] == "0"
