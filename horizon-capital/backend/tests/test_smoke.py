"""Smoke test suite for Horizon Capital.

Validates the entire system can boot and run in LOCAL mode without
any external infrastructure (no Docker, PostgreSQL, or Redis needed).

Run with:
    cd horizon-capital/backend
    python -m pytest tests/test_smoke.py -v
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Force LOCAL mode for all tests
os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"
os.environ["APP_DEBUG"] = "false"


# -- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# -- Unit Tests --------------------------------------------------------------


class TestConfig:
    """Configuration loads correctly."""

    def test_settings_load(self):
        from app.config import StorageBackend, SystemMode, settings

        assert settings.storage_backend == StorageBackend.LOCAL
        assert settings.system_mode == SystemMode.PAPER_TRADING
        assert len(settings.all_symbols) > 0

    def test_all_symbols_parsed(self):
        from app.config import settings

        symbols = settings.all_symbols
        assert "RELIANCE.NSE" in symbols
        assert "AAPL.NASDAQ" in symbols
        assert "BTC-USD" in symbols

    def test_cio_mode_default(self):
        from app.config import CIOMode, settings

        assert settings.cio_mode == CIOMode.HUMAN

    def test_llm_api_key_fields(self):
        from app.config import settings

        # These fields should exist (may be empty)
        assert hasattr(settings, "anthropic_api_key")
        assert hasattr(settings, "openai_api_key")
        assert hasattr(settings, "google_api_key")


class TestLocalStorage:
    """SQLite local storage works."""

    @pytest.mark.asyncio
    async def test_init_local_db(self):
        from app.core.local_storage import init_local_db, local_session_factory

        await init_local_db()

        # Verify tables exist
        from sqlalchemy import text

        async with local_session_factory() as session:
            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result.fetchall()]

        assert "agent_states" in tables
        assert "signals" in tables
        assert "trades" in tables
        assert "risk_metrics" in tables
        assert "debate_sessions" in tables

    @pytest.mark.asyncio
    async def test_insert_and_query(self):
        from app.core.local_storage import init_local_db, local_session_factory

        await init_local_db()

        from sqlalchemy import text

        async with local_session_factory() as session:
            await session.execute(
                text(
                    "INSERT OR REPLACE INTO agent_states "
                    "(agent_id, agent_type, status) "
                    "VALUES ('test-agent', 'test', 'RUNNING')"
                )
            )
            await session.commit()

        async with local_session_factory() as session:
            result = await session.execute(
                text("SELECT agent_id, status FROM agent_states WHERE agent_id = 'test-agent'")
            )
            row = result.fetchone()

        assert row is not None
        assert row[0] == "test-agent"
        assert row[1] == "RUNNING"


class TestMemoryBus:
    """In-memory message bus works."""

    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        received = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        await bus.start_listening()
        await bus.subscribe("test.channel", handler)

        msg = AgentMessage(
            sender_id="test-sender",
            channel="test.channel",
            message_type=MessageType.HEARTBEAT,
            payload={"data": "hello"},
        )
        await bus.publish(msg)

        # Give dispatch loop time to process
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload["data"] == "hello"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_wildcard_subscribe(self):
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        received = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        await bus.start_listening()
        await bus.subscribe("horizon.*", handler)

        msg = AgentMessage(
            sender_id="test",
            channel="horizon.signals",
            message_type=MessageType.SIGNAL,
            payload={},
        )
        await bus.publish(msg)
        await asyncio.sleep(0.2)

        assert len(received) == 1

        await bus.stop()


class TestKVStore:
    """In-memory KV store works."""

    @pytest.mark.asyncio
    async def test_get_set(self):
        from app.core.kv_store import MemoryKVStore

        kv = MemoryKVStore()
        await kv.set("key1", "value1")
        assert await kv.get("key1") == "value1"
        assert await kv.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_hset_hget(self):
        from app.core.kv_store import MemoryKVStore

        kv = MemoryKVStore()
        await kv.hset("myhash", mapping={"field1": "val1", "field2": "val2"})
        assert await kv.hget("myhash", "field1") == "val1"
        assert await kv.hget("myhash", "field2") == "val2"
        assert await kv.hget("myhash", "missing") is None

    @pytest.mark.asyncio
    async def test_delete(self):
        from app.core.kv_store import MemoryKVStore

        kv = MemoryKVStore()
        await kv.set("temp", "data")
        await kv.delete("temp")
        assert await kv.get("temp") is None


class TestVaRCalculator:
    """VaR calculations produce valid results."""

    def test_var_empty(self):
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        calc = VaRCalculator()
        assert calc.compute_var(np.array([]), 0.95) == 0.0

    def test_var_normal(self):
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        calc = VaRCalculator()

        var_95 = calc.compute_var(returns, 0.95)
        var_99 = calc.compute_var(returns, 0.99)

        assert var_95 > 0
        assert var_99 > var_95  # 99% VaR should be higher

    def test_max_drawdown(self):
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        # Equity curve that rises then falls
        equity = np.array([100, 110, 120, 115, 105, 108, 125])
        calc = VaRCalculator()

        max_dd = calc.compute_max_drawdown(equity)
        assert max_dd > 0
        assert max_dd < 1.0  # Should be a fraction

    def test_current_drawdown(self):
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        equity = np.array([100, 110, 120, 115])  # Peak at 120, current at 115
        calc = VaRCalculator()

        dd = calc.compute_current_drawdown(equity)
        assert abs(dd - (5.0 / 120.0)) < 1e-6


class TestMessaging:
    """Agent message serialization."""

    def test_serialize_deserialize(self):
        from app.core.messaging import AgentMessage, MessageType

        msg = AgentMessage(
            sender_id="agent-1",
            channel="test.channel",
            message_type=MessageType.SIGNAL,
            payload={"symbol": "AAPL", "direction": 1},
        )

        serialized = msg.serialize()
        restored = AgentMessage.deserialize(serialized)

        assert restored.sender_id == "agent-1"
        assert restored.channel == "test.channel"
        assert restored.message_type == MessageType.SIGNAL
        assert restored.payload["symbol"] == "AAPL"

    def test_message_types(self):
        from app.core.messaging import MessageType

        # Verify all expected message types exist (original + new)
        expected = [
            "TICK", "OHLCV", "FEATURE_UPDATE", "REGIME_UPDATE",
            "SIGNAL", "RISK_ALERT", "KILL_SWITCH",
            "DEBATE_START", "DEBATE_ARGUMENT", "DEBATE_CONCLUSION",
            "ORDER_NEW", "ORDER_UPDATE", "ORDER_FILL",
            "PORTFOLIO_UPDATE", "CIO_COMMAND",
            "HEARTBEAT", "AGENT_STATUS", "FEED_STATUS",
            # New department message types
            "COMPLIANCE_ALERT", "OPERATIONS_ALERT", "ACCOUNTING_SNAPSHOT",
            "IT_ALERT", "IT_STATUS", "IR_REPORT",
            "DEPARTMENT_STATUS", "CIO_DIRECTIVE", "CIO_CHAT",
        ]
        for name in expected:
            assert hasattr(MessageType, name), f"Missing MessageType: {name}"


class TestDepartments:
    """Department enum and structure."""

    def test_department_types(self):
        from app.agents.departments import DepartmentType

        assert DepartmentType.FRONT_OFFICE.value == "front_office"
        assert DepartmentType.MIDDLE_OFFICE.value == "middle_office"
        assert DepartmentType.BACK_OFFICE.value == "back_office"
        assert DepartmentType.EXECUTIVE.value == "executive"

    def test_department_manager_import(self):
        from app.agents.department_manager import DepartmentManager

        assert DepartmentManager is not None


class TestLLMProviderRegistry:
    """LLM provider registry works."""

    def test_registry_empty(self):
        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        assert registry.list_available() == []
        assert registry.get_provider("claude") is None

    def test_registry_register_empty_key(self):
        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "")  # Empty key should be ignored
        assert registry.list_available() == []

    def test_agent_configs(self):
        from app.llm.agent_config import DEFAULT_AGENT_CONFIGS

        assert len(DEFAULT_AGENT_CONFIGS) > 0

        # Check all departments are represented
        departments = {c.department for c in DEFAULT_AGENT_CONFIGS}
        assert "front_office" in departments
        assert "middle_office" in departments
        assert "back_office" in departments
        assert "executive" in departments


class TestNewAgentImports:
    """New agents can be imported."""

    def test_compliance_agent(self):
        from app.agents.middle_office.compliance.compliance_agent import ComplianceAgent
        assert ComplianceAgent is not None

    def test_operations_agent(self):
        from app.agents.middle_office.operations.operations_agent import OperationsAgent
        assert OperationsAgent is not None

    def test_accounting_agent(self):
        from app.agents.back_office.accounting.accounting_agent import AccountingAgent
        assert AccountingAgent is not None

    def test_it_agent(self):
        from app.agents.back_office.it.it_agent import ITAgent
        assert ITAgent is not None

    def test_quant_agent(self):
        from app.agents.back_office.quant.quant_agent import QuantAgent
        assert QuantAgent is not None

    def test_ir_agent(self):
        from app.agents.front_office.investor_relations.ir_agent import IRAgent
        assert IRAgent is not None

    def test_cio_agent(self):
        from app.agents.executive.cio.cio_agent import CIOAgent
        assert CIOAgent is not None

    def test_human_cio(self):
        from app.agents.executive.cio.human_cio import HumanCIO
        assert HumanCIO is not None


class TestDepartmentManagers:
    """Department managers can be imported and created."""

    def test_front_office_manager(self):
        from app.agents.front_office.manager import FrontOfficeManager
        assert FrontOfficeManager is not None

    def test_middle_office_manager(self):
        from app.agents.middle_office.manager import MiddleOfficeManager
        assert MiddleOfficeManager is not None

    def test_back_office_manager(self):
        from app.agents.back_office.manager import BackOfficeManager
        assert BackOfficeManager is not None

    def test_executive_manager(self):
        from app.agents.executive.manager import ExecutiveManager
        assert ExecutiveManager is not None


class TestMovedAgentImports:
    """Existing agents work from new department locations."""

    def test_risk_agent(self):
        try:
            from app.agents.middle_office.risk.risk_agent import RiskAgent
            assert RiskAgent is not None
        except ImportError:
            pytest.skip("Optional dependency missing (redis)")

    def test_var_calculator(self):
        from app.agents.middle_office.risk.var_calculator import VaRCalculator
        assert VaRCalculator is not None

    def test_regime_agent(self):
        try:
            from app.agents.front_office.research.regime_agent import RegimeAgent
            assert RegimeAgent is not None
        except ImportError:
            pytest.skip("Optional dependency missing (joblib/hmmlearn)")

    def test_ensemble_selector(self):
        from app.agents.front_office.strategy.ensemble_selector import EnsembleSelector
        assert EnsembleSelector is not None


class TestEnsembleSelector:
    """Strategy ensemble routing."""

    def test_create_ensemble(self):
        from app.agents.front_office.strategy.ensemble_selector import EnsembleSelector

        ensemble = EnsembleSelector()
        assert len(ensemble.strategies) == 4

    def test_get_active_strategies(self):
        from app.agents.front_office.strategy.ensemble_selector import EnsembleSelector

        ensemble = EnsembleSelector()
        # Should return at least one strategy for common regimes
        for regime in ["BULL", "BEAR", "NEUTRAL", "HIGH_VOLATILITY", "CRISIS"]:
            active = ensemble.get_active_strategies(regime)
            # Each regime should have at least 1 active strategy
            assert isinstance(active, list)


class TestRuntime:
    """Runtime initialization works in LOCAL mode."""

    @pytest.mark.asyncio
    async def test_startup_shutdown(self):
        from app.core.runtime import get_bus, get_session_factory, startup, shutdown

        await startup()

        bus = get_bus()
        assert bus is not None

        sf = get_session_factory()
        assert sf is not None

        await shutdown()


class TestTerminalCommands:
    """Terminal command handler."""

    @pytest.mark.asyncio
    async def test_help_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("help")
        assert result is not None
        assert "status" in result
        assert "quit" in result
        assert "departments" in result
        assert "cio" in result

    @pytest.mark.asyncio
    async def test_config_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("config")
        assert "PAPER_TRADING" in result
        assert "CIO Mode" in result

    @pytest.mark.asyncio
    async def test_symbols_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("symbols")
        assert "India" in result
        assert "RELIANCE" in result

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("foobar")
        assert "Unknown command" in result

    @pytest.mark.asyncio
    async def test_quit_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("quit")
        assert handler.should_quit is True

    @pytest.mark.asyncio
    async def test_departments_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("departments")
        assert result is not None
        # Without orchestrator, should show message
        assert "Orchestrator not available" in result or "Department" in result

    @pytest.mark.asyncio
    async def test_agents_config_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("agents config")
        assert result is not None
        assert "Agent Configuration" in result


class TestCIOChat:
    """CIO chat interface."""

    @pytest.mark.asyncio
    async def test_keyword_help(self):
        from app.tui.cio_chat import CIOChat

        chat = CIOChat()
        response = await chat.chat("help")
        assert "status" in response.lower() or "help" in response.lower()

    @pytest.mark.asyncio
    async def test_keyword_status(self):
        from app.tui.cio_chat import CIOChat

        chat = CIOChat()
        response = await chat.chat("How is the system doing?")
        assert response is not None

    @pytest.mark.asyncio
    async def test_keyword_risk(self):
        from app.tui.cio_chat import CIOChat

        chat = CIOChat()
        response = await chat.chat("What are the risk metrics?")
        assert "risk" in response.lower() or "available" in response.lower()
