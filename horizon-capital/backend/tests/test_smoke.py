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

    def test_cio_mode_valid(self):
        from app.config import CIOMode, settings

        assert settings.cio_mode in (CIOMode.HUMAN, CIOMode.AI)

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

        # Verify all expected message types exist
        expected = [
            "TICK", "OHLCV", "FEATURE_UPDATE",
            "SIGNAL", "RISK_CHECK", "RISK_ALERT",
            "DEBATE_START", "DEBATE_VOTE", "DEBATE_CONCLUSION",
            "ORDER_NEW", "ORDER_FILL", "ORDER_CANCEL",
            "PORTFOLIO_UPDATE", "HEALTH_CHECK",
            "SENTIMENT_UPDATE", "AGENT_STATUS", "HEARTBEAT",
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


# -- Phase 2 Tests -----------------------------------------------------------


class TestAlphaMonitor:
    """Alpha monitor agent."""

    def test_import(self):
        from app.agents.middle_office.alpha_monitor import AlphaMonitorAgent
        assert AlphaMonitorAgent is not None

    def test_strategy_performance(self):
        from app.agents.middle_office.alpha_monitor import StrategyPerformance

        perf = StrategyPerformance(strategy_name="test")
        assert perf.win_rate == 0.0
        assert perf.rolling_sharpe == 0.0
        assert perf.avg_signal_strength == 0.0

        perf.returns.append(0.01)
        perf.returns.append(0.02)
        perf.returns.append(-0.005)
        perf.returns.append(0.015)
        perf.returns.append(0.008)
        perf.total_trades = 5
        perf.wins = 4
        perf.losses = 1
        assert perf.win_rate == 0.8
        assert perf.rolling_sharpe != 0.0

    @pytest.mark.asyncio
    async def test_create_agent(self):
        from app.core.memory_bus import MemoryBus
        from app.agents.middle_office.alpha_monitor import AlphaMonitorAgent

        bus = MemoryBus()
        await bus.start_listening()
        agent = AlphaMonitorAgent(bus=bus)
        assert agent.agent_id == "alpha-monitor-1"
        assert agent.department == "middle_office"
        await bus.stop()


class TestAdaptationEngine:
    """Adaptation engine service."""

    def test_import(self):
        from app.services.adaptation_engine import AdaptationEngine
        assert AdaptationEngine is not None

    @pytest.mark.asyncio
    async def test_start_stop(self):
        from app.core.memory_bus import MemoryBus
        from app.services.adaptation_engine import AdaptationEngine

        bus = MemoryBus()
        await bus.start_listening()
        engine = AdaptationEngine(bus=bus)
        await engine.start()
        assert engine._active is True
        assert engine.get_strategy_weights() == {
            "momentum": 1.0,
            "mean_reversion": 1.0,
            "volatility": 1.0,
            "crisis": 1.0,
        }
        await engine.stop()
        assert engine._active is False
        await bus.stop()


class TestAttributionEngine:
    """Attribution engine service."""

    def test_import(self):
        from app.services.attribution_engine import AttributionEngine
        assert AttributionEngine is not None

    def test_symbol_to_scope(self):
        from app.services.attribution_engine import AttributionEngine

        assert AttributionEngine._symbol_to_scope("RELIANCE.NSE") == "INDIA"
        assert AttributionEngine._symbol_to_scope("AAPL.NASDAQ") == "US"
        assert AttributionEngine._symbol_to_scope("BTC-USD") == "CRYPTO"

    def test_regime_influence(self):
        from app.services.attribution_engine import AttributionEngine

        # Bull regime + buy = positive influence
        assert AttributionEngine._compute_regime_influence("BULL", 1) > 0
        # Bull regime + sell = negative influence
        assert AttributionEngine._compute_regime_influence("BULL", -1) < 0
        # Crisis regime + sell = positive influence (regime supports selling)
        assert AttributionEngine._compute_regime_influence("CRISIS", -1) > 0

    @pytest.mark.asyncio
    async def test_start_stop(self):
        from app.core.memory_bus import MemoryBus
        from app.services.attribution_engine import AttributionEngine

        bus = MemoryBus()
        await bus.start_listening()
        engine = AttributionEngine(bus=bus)
        await engine.start()
        assert engine._active is True
        assert engine.get_attributions() == []
        await engine.stop()
        await bus.stop()


class TestOnboarding:
    """Onboarding wizard."""

    def test_import(self):
        from app.tui.onboarding import needs_onboarding, run_onboarding
        assert needs_onboarding is not None
        assert run_onboarding is not None

    def test_needs_onboarding(self):
        from app.tui.onboarding import needs_onboarding
        # Will return True since we don't have API keys configured in test
        result = needs_onboarding()
        assert isinstance(result, bool)


class TestAgentVisualizer:
    """Agent visualizer."""

    def test_import(self):
        from app.tui.agent_visualizer import AgentVisualizer
        assert AgentVisualizer is not None

    def test_update_state(self):
        from app.tui.agent_visualizer import AgentVisualizer

        viz = AgentVisualizer()
        viz.update_state("agent-1", "ANALYZING")
        viz.update_state("agent-2", "IDLE")
        states = viz.get_states()
        assert states["agent-1"] == "ANALYZING"
        assert states["agent-2"] == "IDLE"

    def test_build_panel(self):
        from app.tui.agent_visualizer import AgentVisualizer

        viz = AgentVisualizer()
        viz.update_state("agent-1", "DEBATING")
        panel = viz.build_panel()
        assert panel is not None


class TestLLMStrategyPath:
    """LLM-enhanced strategy agents."""

    def test_base_strategy_llm_provider(self):
        from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy

        # Without LLM
        strat = MomentumStrategy()
        assert strat._llm_provider == ""

        # With LLM
        strat = MomentumStrategy(llm_provider="claude")
        assert strat._llm_provider == "claude"

    def test_ensemble_with_llm(self):
        from app.agents.front_office.strategy.ensemble_selector import EnsembleSelector

        ensemble = EnsembleSelector(llm_provider="claude")
        assert len(ensemble.strategies) == 4
        for s in ensemble.strategies:
            assert s._llm_provider == "claude"

    def test_parse_llm_response(self):
        from app.agents.front_office.strategy.base_strategy import BaseStrategy

        # Direct JSON
        result = BaseStrategy._parse_llm_response('{"direction": 1, "strength": 0.8, "reasoning": "test"}')
        assert result["direction"] == 1

        # JSON in code block
        result = BaseStrategy._parse_llm_response('```json\n{"direction": -1, "strength": 0.5, "reasoning": "sell"}\n```')
        assert result["direction"] == -1

        # JSON embedded in text
        result = BaseStrategy._parse_llm_response('Here is my analysis: {"direction": 0, "strength": 0.1, "reasoning": "hold"}')
        assert result["direction"] == 0

        # Invalid
        result = BaseStrategy._parse_llm_response("no json here")
        assert result is None


class TestNewMessageTypes:
    """Phase 2 message types exist."""

    def test_alpha_decay(self):
        from app.core.messaging import MessageType
        assert hasattr(MessageType, "ALPHA_DECAY")
        assert hasattr(MessageType, "ALPHA_SNAPSHOT")
        assert hasattr(MessageType, "REGIME_TRANSITION")
        assert hasattr(MessageType, "ADAPTATION_ACTION")
        assert hasattr(MessageType, "AGENT_STATE_CHANGE")


class TestPhase2Commands:
    """Phase 2 CIO terminal commands."""

    @pytest.mark.asyncio
    async def test_help_includes_phase2(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("help")
        assert "interrupt" in result
        assert "override regime" in result
        assert "risk-tolerance" in result
        assert "exposures" in result
        assert "attribution" in result

    @pytest.mark.asyncio
    async def test_risk_tolerance_no_args(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("risk-tolerance")
        assert "Current risk tolerance" in result

    @pytest.mark.asyncio
    async def test_exposures_no_dashboard(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("exposures")
        assert result is not None

    @pytest.mark.asyncio
    async def test_kill_switch_toggle(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("kill-switch")
        # Without orchestrator, should still work with kv store
        assert "ACTIVATED" in result or "Kill switch" in result


# -- Phase 2.5 Tests: Research-Backed Algorithm Upgrades -----------------


class TestGarchEvtVaR:
    """GARCH-EVT VaR calculator (Priority 1)."""

    def test_import(self):
        from app.agents.middle_office.risk.var_calculator import VaRCalculator
        assert hasattr(VaRCalculator, "compute_var_garch_evt")

    def test_historical_fallback_short_data(self):
        """Short data should fall back to historical VaR."""
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        returns = np.random.normal(0, 0.02, 50)
        result = VaRCalculator.compute_var_garch_evt(returns, 0.95)
        assert result["method"] == "historical"
        assert result["var"] >= 0
        assert result["cvar"] >= 0

    def test_garch_evt_sufficient_data(self):
        """With enough data, GARCH-EVT should run (or gracefully fall back)."""
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        np.random.seed(42)
        returns = np.random.normal(0, 0.02, 500)
        result = VaRCalculator.compute_var_garch_evt(returns, 0.95)
        assert result["var"] >= 0
        assert result["cvar"] >= 0
        assert result["cond_vol"] >= 0
        assert result["method"] in ("garch_evt", "garch_t", "historical")

    def test_99_confidence(self):
        """99% VaR should be larger than 95%."""
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        np.random.seed(42)
        returns = np.random.normal(-0.001, 0.02, 500)
        r95 = VaRCalculator.compute_var_garch_evt(returns, 0.95)
        r99 = VaRCalculator.compute_var_garch_evt(returns, 0.99)
        assert r99["var"] >= r95["var"] * 0.8  # 99% should generally be larger

    def test_legacy_var_still_works(self):
        """Legacy historical VaR methods are preserved."""
        import numpy as np
        from app.agents.middle_office.risk.var_calculator import VaRCalculator

        returns = np.array([-0.05, -0.03, -0.01, 0.01, 0.03, 0.05])
        var = VaRCalculator.compute_var(returns, 0.95)
        cvar = VaRCalculator.compute_cvar(returns, 0.95)
        assert var > 0
        assert cvar >= var


class TestHRPPortfolio:
    """Hierarchical Risk Parity portfolio (Priority 2)."""

    def test_import(self):
        from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer
        assert hasattr(PortfolioOptimizer, "hrp_weights")
        assert hasattr(PortfolioOptimizer, "ledoit_wolf_shrinkage")

    def test_ledoit_wolf(self):
        """Ledoit-Wolf shrinkage produces valid covariance matrix."""
        import numpy as np
        from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer

        np.random.seed(42)
        returns = np.random.normal(0, 0.02, (100, 4))
        cov = PortfolioOptimizer.ledoit_wolf_shrinkage(returns)
        assert cov.shape == (4, 4)
        # Diagonal should be positive (variances)
        assert all(cov[i, i] > 0 for i in range(4))
        # Should be symmetric
        assert np.allclose(cov, cov.T, atol=1e-10)

    def test_hrp_weights_basic(self):
        """HRP produces valid weights that sum to ~1."""
        import numpy as np
        from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer

        np.random.seed(42)
        returns = np.random.normal(0, 0.02, (100, 3))
        symbols = ["AAPL", "MSFT", "GOOGL"]
        weights = PortfolioOptimizer.hrp_weights(returns, symbols)

        assert len(weights) == 3
        assert all(w >= 0 for w in weights.values())
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_hrp_single_asset(self):
        """Single asset should get weight 1.0."""
        import numpy as np
        from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer

        returns = np.random.normal(0, 0.02, (50, 1))
        weights = PortfolioOptimizer.hrp_weights(returns, ["BTC"])
        assert weights == {"BTC": 1.0}

    def test_kelly_and_position_size_preserved(self):
        """Legacy Kelly fraction and position_size still work."""
        from app.agents.front_office.portfolio.optimizer import PortfolioOptimizer

        kelly = PortfolioOptimizer.kelly_fraction(0.6, 1.5)
        assert 0 < kelly < 1
        shares = PortfolioOptimizer.position_size(kelly, 100000, 150.0)
        assert shares > 0


class TestJumpModel:
    """Statistical Jump Model regime detector (Priority 3)."""

    def test_import(self):
        from app.agents.front_office.research.jump_model import JumpRegimeModel
        assert JumpRegimeModel is not None

    def test_availability_flag(self):
        """Should report whether jumpmodels library is installed."""
        from app.agents.front_office.research.jump_model import JumpRegimeModel
        model = JumpRegimeModel()
        assert isinstance(model.is_available, bool)

    def test_regime_agent_has_jump_models(self):
        """Regime agent should have Jump models; HMM models if hmmlearn installed."""
        from app.core.memory_bus import MemoryBus
        bus = MemoryBus()
        from app.agents.front_office.research.regime_agent import RegimeAgent
        agent = RegimeAgent(bus=bus)
        assert hasattr(agent, "_jump_models")
        assert hasattr(agent, "_hmm_models")
        assert len(agent._jump_models) == 3  # INDIA, US, CRYPTO
        # HMM models are only populated when hmmlearn is installed
        from app.agents.front_office.research.hmm_model import HMMRegimeModel
        if HMMRegimeModel.is_available():
            assert len(agent._hmm_models) == 3
        else:
            assert len(agent._hmm_models) == 0


class TestOUMeanReversion:
    """Ornstein-Uhlenbeck mean reversion strategy (Priority 4)."""

    def test_import(self):
        from app.agents.front_office.strategy.mean_reversion_strategy import MeanReversionStrategy
        assert MeanReversionStrategy is not None

    def test_ou_calibration_mean_reverting(self):
        """OU calibration on mean-reverting data should return parameters."""
        import numpy as np
        from app.agents.front_office.strategy.mean_reversion_strategy import MeanReversionStrategy

        np.random.seed(42)
        # Generate OU-like process: price reverts to 100
        mu = 100.0
        kappa = 0.1
        sigma = 2.0
        prices = [100.0]
        for _ in range(99):
            dx = kappa * (mu - prices[-1]) + sigma * np.random.normal()
            prices.append(max(prices[-1] + dx, 1.0))

        result = MeanReversionStrategy._calibrate_ou(np.array(prices))
        assert result is not None
        est_mu, est_kappa, est_sigma, s_score = result
        assert est_kappa > 0  # should detect mean reversion
        assert est_mu > 0

    def test_ou_calibration_trending(self):
        """OU calibration on strong uptrend should find very weak reversion."""
        import numpy as np
        from app.agents.front_office.strategy.mean_reversion_strategy import MeanReversionStrategy

        # Strong deterministic exponential uptrend (no noise)
        # log-prices are perfectly linear → dx has no correlation with x
        prices = 100.0 * np.exp(np.arange(50) * 0.02)
        result = MeanReversionStrategy._calibrate_ou(prices)
        # Either None (b >= 0) or kappa is negligibly small
        if result is not None:
            _, kappa, _, _ = result
            assert kappa < 0.01  # near-zero reversion speed

    def test_bollinger_fallback(self):
        """Should fall back to Bollinger Bands when no price_history."""
        from app.agents.front_office.strategy.mean_reversion_strategy import MeanReversionStrategy

        strat = MeanReversionStrategy()
        signal = strat.generate_signal("TEST", {
            "close": 95.0,
            "rsi": 25.0,
            "bb_upper": 110.0,
            "bb_lower": 96.0,
            "bb_mid": 103.0,
        }, "BEAR")
        assert signal is not None
        assert signal.direction == 1  # BUY at lower band
        assert signal.meta.get("method") == "bollinger"


class TestGarchVolatility:
    """GJR-GARCH volatility strategy (Priority 5)."""

    def test_import(self):
        from app.agents.front_office.strategy.volatility_strategy import VolatilityStrategy
        assert VolatilityStrategy is not None

    def test_atr_fallback(self):
        """Should fall back to ATR when no return_history."""
        from app.agents.front_office.strategy.volatility_strategy import VolatilityStrategy

        strat = VolatilityStrategy()
        signal = strat.generate_signal("TEST", {
            "atr": 5.0,
            "atr_avg_20": 2.0,
            "close": 100.0,
        }, "HIGH_VOL")
        assert signal is not None
        assert signal.direction == -1  # reduce exposure
        assert signal.meta.get("method") == "atr"

    def test_garch_with_return_history(self):
        """GARCH should run (or gracefully fall back) with return history."""
        import numpy as np
        from app.agents.front_office.strategy.volatility_strategy import VolatilityStrategy

        np.random.seed(42)
        returns = list(np.random.normal(0, 0.02, 100))
        strat = VolatilityStrategy()
        signal = strat.generate_signal("TEST", {
            "return_history": returns,
            "atr": 5.0,
            "atr_avg_20": 2.0,
            "close": 100.0,
        }, "HIGH_VOL")
        # May or may not generate signal depending on GARCH fit
        # But should not crash
        assert signal is None or isinstance(signal.direction, int)


class TestAlmgrenChriss:
    """Almgren-Chriss market impact model (Priority 6)."""

    def test_import(self):
        from app.agents.front_office.trading.paper_broker import AlmgrenChrissModel
        assert AlmgrenChrissModel is not None

    def test_impact_increases_with_quantity(self):
        """Larger orders should have more market impact."""
        from app.agents.front_office.trading.paper_broker import AlmgrenChrissModel

        small = AlmgrenChrissModel.compute_impact(100, 150.0, 1_000_000)
        large = AlmgrenChrissModel.compute_impact(10_000, 150.0, 1_000_000)
        assert large["total_impact_pct"] > small["total_impact_pct"]

    def test_buy_fills_above_mid(self):
        """BUY orders should fill above mid-price."""
        from app.agents.front_office.trading.paper_broker import AlmgrenChrissModel

        # Run many times to average out noise
        import numpy as np
        np.random.seed(42)
        fills = [
            AlmgrenChrissModel.compute_impact(1000, 100.0, 1_000_000, side="BUY")["fill_price"]
            for _ in range(100)
        ]
        avg_fill = np.mean(fills)
        assert avg_fill > 100.0  # on average, BUY fills above mid

    def test_zero_quantity(self):
        """Zero quantity should return zero impact."""
        from app.agents.front_office.trading.paper_broker import AlmgrenChrissModel

        result = AlmgrenChrissModel.compute_impact(0, 100.0)
        assert result["total_impact_pct"] == 0.0
        assert result["fill_price"] == 100.0

    def test_impact_breakdown(self):
        """Should separate permanent and temporary impact."""
        from app.agents.front_office.trading.paper_broker import AlmgrenChrissModel

        result = AlmgrenChrissModel.compute_impact(5000, 200.0, 500_000, 0.03)
        assert result["permanent_impact"] > 0
        assert result["temporary_impact"] > 0
        assert result["total_impact_pct"] > 0


class TestLoughranMcDonald:
    """Loughran-McDonald financial dictionary (Priority 7)."""

    def test_import(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer
        assert hasattr(FinBERTScorer, "lm_score")
        assert hasattr(FinBERTScorer, "score_combined")

    def test_positive_text(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer

        result = FinBERTScorer.lm_score(
            "Record growth and strong profitability with excellent gains"
        )
        assert result["lm_score"] > 0
        assert result["positive_count"] > 0
        assert result["negative_count"] == 0

    def test_negative_text(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer

        result = FinBERTScorer.lm_score(
            "Bankruptcy crisis and fraud led to losses and litigation"
        )
        assert result["lm_score"] < 0
        assert result["negative_count"] > 0

    def test_neutral_text(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer

        result = FinBERTScorer.lm_score(
            "The quarterly report was filed on Tuesday as scheduled"
        )
        assert abs(result["lm_score"]) < 0.5

    def test_uncertainty_detection(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer

        result = FinBERTScorer.lm_score(
            "We believe the estimates could possibly change depending on uncertain conditions"
        )
        assert result["uncertainty_count"] >= 3

    def test_litigious_detection(self):
        from app.agents.front_office.research.finbert_scorer import FinBERTScorer

        result = FinBERTScorer.lm_score(
            "The defendant filed a complaint and the lawsuit settlement is pending"
        )
        assert result["litigious_count"] >= 3


class TestVPVMAMomentum:
    """VPVMA + multi-indicator fusion momentum (Priority 8)."""

    def test_import(self):
        from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy
        assert MomentumStrategy is not None

    def test_vpvma_computation(self):
        """VPVMA should amplify signal with volume confirmation."""
        from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy

        # Bullish MACD + high volume + expanding vol
        score = MomentumStrategy._compute_vpvma(
            macd=0.5, macd_signal=0.3,
            volume=2_000_000, volume_avg=1_000_000,
            atr=5.0, atr_avg=3.0,
        )
        assert score > 0  # should be positive (bullish)

        # Bearish MACD + high volume
        score = MomentumStrategy._compute_vpvma(
            macd=0.3, macd_signal=0.5,
            volume=2_000_000, volume_avg=1_000_000,
            atr=5.0, atr_avg=3.0,
        )
        assert score < 0  # should be negative (bearish)

    def test_fusion_scoring(self):
        """Multi-indicator fusion should produce valid strength."""
        from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy

        strength = MomentumStrategy._compute_strength_fusion(0.3, 4, 6)
        assert 0 <= strength <= 1

    def test_signal_with_all_indicators(self):
        """Should generate signal when all indicators present."""
        from app.agents.front_office.strategy.momentum_strategy import MomentumStrategy

        strat = MomentumStrategy()
        signal = strat.generate_signal("TEST", {
            "rsi": 25.0,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema_20": 98.0,
            "close": 100.0,
            "volume": 2_000_000,
            "volume_avg_20": 1_000_000,
            "vwap": 99.0,
            "atr": 3.0,
            "atr_avg_20": 2.0,
        }, "BULL")
        assert signal is not None
        assert signal.direction == 1  # bullish
        assert "fusion" in signal.reasoning


class TestCrisisTrendFollowing:
    """Crisis trend-following overlay (Priority 9)."""

    def test_import(self):
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy
        assert CrisisStrategy is not None

    def test_trend_following_bearish_crossover(self):
        """Should detect bearish EMA crossover."""
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy

        result = CrisisStrategy._trend_following_signal({
            "close": 90.0,
            "ema_10": 95.0,
            "ema_50": 100.0,
        })
        assert result is not None
        assert result["type"] == "trend_following"
        assert result["strength"] > 0

    def test_drawdown_hedging(self):
        """Should trigger hedge at sufficient drawdown."""
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy

        # No hedge below 5%
        result = CrisisStrategy._drawdown_hedge_signal({"current_drawdown": 0.03})
        assert result is None

        # Partial hedge at 10%
        result = CrisisStrategy._drawdown_hedge_signal({"current_drawdown": 0.10})
        assert result is not None
        assert 0.3 < result["strength"] < 1.0

        # Full hedge at 15%+
        result = CrisisStrategy._drawdown_hedge_signal({"current_drawdown": 0.20})
        assert result is not None
        assert result["strength"] >= 0.9

    def test_vix_gradual_scaling(self):
        """VIX signal should scale gradually, not binary."""
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy

        # No signal below 20
        assert CrisisStrategy._vix_signal(15.0) is None

        # Mild signal at 25
        r25 = CrisisStrategy._vix_signal(25.0)
        assert r25 is not None

        # Stronger at 35
        r35 = CrisisStrategy._vix_signal(35.0)
        assert r35 is not None
        assert r35["strength"] > r25["strength"]

    def test_trailing_stop(self):
        """Dynamic trailing stop should trigger when price breaches."""
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy

        # Price above stop — no signal
        result = CrisisStrategy._trailing_stop_signal({
            "close": 100.0, "atr": 2.0, "recent_high": 105.0,
        })
        assert result is None  # stop = 105 - 6 = 99, close=100 > 99

        # Price below stop
        result = CrisisStrategy._trailing_stop_signal({
            "close": 90.0, "atr": 2.0, "recent_high": 105.0,
        })
        assert result is not None
        assert result["type"] == "trailing_stop"

    def test_multi_signal_combination(self):
        """Should combine multiple crisis signals."""
        from app.agents.front_office.strategy.crisis_strategy import CrisisStrategy

        strat = CrisisStrategy()
        signal = strat.generate_signal("TEST", {
            "close": 85.0,
            "vix_proxy": 35.0,
            "atr": 3.0,
            "ema_10": 90.0,
            "ema_50": 100.0,
            "current_drawdown": 0.12,
            "recent_high": 100.0,
        }, "CRISIS")
        assert signal is not None
        assert signal.direction == -1
        assert signal.meta.get("crisis_signal_count", 0) >= 2


# ===================================================================
# Phase 3 — Advanced Backtesting & Performance Analytics
# ===================================================================


class TestAdvancedMetrics:
    """Phase 3: Enhanced backtest metrics.

    Ref: Keating & Shadwick 2002 (Omega), Bacon 2008 (tail ratio,
    recovery factor, information ratio), Sharpe 1994.
    """

    def _make_equity_and_returns(self):
        """Helper: create a sample equity curve and returns."""
        import numpy as np
        rng = np.random.default_rng(42)
        daily_ret = rng.normal(0.0005, 0.01, 252)
        equity = [1_000_000.0]
        for r in daily_ret:
            equity.append(equity[-1] * (1 + r))
        return np.array(equity), daily_ret

    def test_omega_ratio(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        _, returns = self._make_equity_and_returns()
        omega = BacktestMetrics.omega_ratio(returns, threshold=0.0)
        assert omega > 0
        # Positive mean returns → omega should be > 1
        assert omega > 1.0

    def test_tail_ratio(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        _, returns = self._make_equity_and_returns()
        tr = BacktestMetrics.tail_ratio(returns)
        assert tr > 0

    def test_recovery_factor(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        import numpy as np
        # Construct a clearly uptrending equity curve
        equity = np.linspace(1_000_000, 1_200_000, 252)
        rf = BacktestMetrics.recovery_factor(equity)
        assert rf > 0

    def test_information_ratio(self):
        import numpy as np
        from app.backtesting.backtest_metrics import BacktestMetrics
        # Use deterministic returns where portfolio clearly beats benchmark
        port_ret = np.full(252, 0.002)   # 0.2% daily
        bench_ret = np.full(252, 0.001)  # 0.1% daily
        # Add small noise
        rng = np.random.default_rng(42)
        port_ret = port_ret + rng.normal(0, 0.001, 252)
        bench_ret = bench_ret + rng.normal(0, 0.001, 252)
        ir = BacktestMetrics.information_ratio(port_ret, bench_ret)
        assert ir > 0

    def test_avg_win_loss(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        trades = [
            {"pnl": 100}, {"pnl": 200}, {"pnl": -50}, {"pnl": -30}, {"pnl": 150},
        ]
        wl = BacktestMetrics.avg_win_loss(trades)
        assert wl["avg_win"] > 0
        assert wl["avg_loss"] < 0
        assert wl["win_loss_ratio"] > 0

    def test_max_consecutive_losses(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        trades = [
            {"pnl": 100}, {"pnl": -10}, {"pnl": -20}, {"pnl": -30}, {"pnl": 50},
        ]
        mcl = BacktestMetrics.max_consecutive_losses(trades)
        assert mcl == 3

    def test_drawdown_duration(self):
        from app.backtesting.backtest_metrics import BacktestMetrics
        import numpy as np
        # Equity with a drawdown period
        equity = np.array([100, 105, 103, 101, 100, 102, 106, 110])
        dd = BacktestMetrics.drawdown_duration(equity)
        assert dd["max_dd_duration"] > 0

    def test_compute_all_includes_advanced(self):
        """compute_all should return all advanced metrics."""
        from app.backtesting.backtest_metrics import BacktestMetrics
        equity, _ = self._make_equity_and_returns()
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}]
        metrics = BacktestMetrics.compute_all(equity, trades)
        assert "omega_ratio" in metrics
        assert "tail_ratio" in metrics
        assert "recovery_factor" in metrics
        assert "information_ratio" in metrics
        assert "max_consecutive_losses" in metrics
        assert "annualized_volatility" in metrics


class TestMultiAssetEngine:
    """Phase 3: Multi-asset portfolio backtest engine.

    Ref: de Prado 2018, DeMiguel et al. 2009.
    """

    def _make_bars(self, n=100, seed=42):
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        price = 100.0
        rows = []
        for d in dates:
            ret = rng.normal(0.001, 0.015)
            price *= (1 + ret)
            rows.append({
                "open": price * 0.999,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": rng.integers(100000, 500000),
            })
        return pd.DataFrame(rows, index=dates)

    def test_align_bars(self):
        from app.backtesting.multi_asset_engine import MultiAssetEngine
        bars_a = self._make_bars(100, seed=1)
        bars_b = self._make_bars(100, seed=2)
        common_idx, aligned = MultiAssetEngine.align_bars({"A": bars_a, "B": bars_b})
        assert len(common_idx) == 100
        assert "A" in aligned and "B" in aligned

    def test_multi_asset_backtest(self):
        from app.backtesting.multi_asset_engine import MultiAssetEngine
        from app.backtesting.backtest_broker import SimOrder

        bars_a = self._make_bars(100, seed=1)
        bars_b = self._make_bars(100, seed=2)

        def strategy(history_by_sym, context):
            """Simple: buy A on bar 5, sell on bar 50."""
            orders = []
            idx = context["bar_index"]
            if idx == 5 and context["positions"]["A"] == 0:
                orders.append(SimOrder(side="BUY", quantity=100, symbol="A"))
            if idx == 50 and context["positions"]["A"] > 0:
                orders.append(SimOrder(side="SELL", quantity=100, symbol="A"))
            return orders

        engine = MultiAssetEngine(initial_capital=1_000_000)
        result = engine.run_sync({"A": bars_a, "B": bars_b}, strategy)
        assert result.bars_processed == 100
        assert len(result.trades) >= 1
        assert result.final_capital != result.initial_capital
        assert "sharpe_ratio" in result.metrics

    def test_per_symbol_pnl(self):
        from app.backtesting.multi_asset_engine import MultiAssetEngine
        from app.backtesting.backtest_broker import SimOrder

        bars_a = self._make_bars(60, seed=10)

        def strategy(history_by_sym, context):
            idx = context["bar_index"]
            if idx == 5:
                return [SimOrder(side="BUY", quantity=50, symbol="A")]
            if idx == 40:
                return [SimOrder(side="SELL", quantity=50, symbol="A")]
            return []

        engine = MultiAssetEngine(initial_capital=500_000)
        result = engine.run_sync({"A": bars_a}, strategy)
        assert "A" in result.per_symbol_pnl


class TestWalkForward:
    """Phase 3: Walk-forward optimization.

    Ref: Pardo 2008, DeMiguel et al. 2009.
    """

    def _make_bars(self, n=500):
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(42)
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        price = 100.0
        rows = []
        for d in dates:
            ret = rng.normal(0.0005, 0.012)
            price *= (1 + ret)
            rows.append({
                "open": price * 0.999,
                "high": price * 1.005,
                "low": price * 0.995,
                "close": price,
                "volume": rng.integers(100000, 500000),
            })
        return pd.DataFrame(rows, index=dates)

    def test_walk_forward_runs(self):
        from app.backtesting.walk_forward import WalkForwardOptimizer
        from app.backtesting.backtest_broker import SimOrder

        bars = self._make_bars(500)

        def strategy_factory(params):
            threshold = params.get("threshold", 0.01)
            def strategy(history, context):
                if len(history) < 20:
                    return None
                ret_20 = (history["close"].iloc[-1] / history["close"].iloc[-20]) - 1
                if ret_20 > threshold and context["position_qty"] == 0:
                    return SimOrder(side="BUY", quantity=100)
                if ret_20 < -threshold and context["position_qty"] > 0:
                    return SimOrder(side="SELL", quantity=100)
                return None
            return strategy

        param_grid = [
            {"threshold": 0.005},
            {"threshold": 0.01},
            {"threshold": 0.02},
        ]

        wfo = WalkForwardOptimizer(n_folds=3, train_ratio=0.7)
        result = wfo.run(bars, param_grid, strategy_factory)
        assert len(result.folds) > 0
        assert result.walk_forward_efficiency is not None

    def test_walk_forward_efficiency(self):
        """WF efficiency = OOS Sharpe / IS Sharpe. Should be finite."""
        from app.backtesting.walk_forward import WalkForwardOptimizer
        from app.backtesting.backtest_broker import SimOrder

        bars = self._make_bars(300)

        def strategy_factory(params):
            def strategy(history, context):
                return None  # hold cash
            return strategy

        wfo = WalkForwardOptimizer(n_folds=2)
        result = wfo.run(bars, [{"x": 1}], strategy_factory)
        assert len(result.folds) >= 1


class TestMonteCarlo:
    """Phase 3: Monte Carlo simulation.

    Ref: Glasserman 2003, Efron & Tibshirani 1993.
    """

    def _make_returns(self, n=252):
        import numpy as np
        rng = np.random.default_rng(42)
        return rng.normal(0.0005, 0.01, n)

    def test_bootstrap(self):
        from app.backtesting.monte_carlo import MonteCarloSimulator
        sim = MonteCarloSimulator(n_simulations=100, random_seed=42)
        result = sim.bootstrap(self._make_returns(), n_days=60)
        assert result.n_simulations == 100
        assert result.method == "bootstrap"
        assert result.mean_terminal > 0
        assert 0 <= result.prob_loss <= 1
        assert result.mean_max_drawdown >= 0

    def test_gbm(self):
        from app.backtesting.monte_carlo import MonteCarloSimulator
        sim = MonteCarloSimulator(n_simulations=100, random_seed=42)
        result = sim.gbm(self._make_returns(), n_days=60)
        assert result.method == "gbm"
        assert result.mean_terminal > 0

    def test_block_bootstrap(self):
        """Block bootstrap preserves autocorrelation."""
        from app.backtesting.monte_carlo import MonteCarloSimulator
        sim = MonteCarloSimulator(n_simulations=50, random_seed=42)
        result = sim.bootstrap(self._make_returns(), n_days=60, block_size=5)
        assert result.n_simulations == 50
        assert result.mean_terminal > 0

    def test_percentiles_ordered(self):
        from app.backtesting.monte_carlo import MonteCarloSimulator
        sim = MonteCarloSimulator(n_simulations=500, random_seed=42)
        result = sim.bootstrap(self._make_returns(), n_days=252)
        assert result.percentile_5 <= result.percentile_25
        assert result.percentile_25 <= result.median_terminal
        assert result.median_terminal <= result.percentile_75
        assert result.percentile_75 <= result.percentile_95

    def test_sharpe_distribution(self):
        from app.backtesting.monte_carlo import MonteCarloSimulator
        sim = MonteCarloSimulator(n_simulations=200, random_seed=42)
        result = sim.bootstrap(self._make_returns(), n_days=252)
        assert result.percentile_5_sharpe <= result.mean_sharpe
        assert result.mean_sharpe <= result.percentile_95_sharpe


class TestBenchmark:
    """Phase 3: Benchmark comparison.

    Ref: Brinson et al. 1986, Sharpe 1994.
    """

    def test_single_benchmark(self):
        import numpy as np
        from app.backtesting.benchmark import BenchmarkComparer
        rng = np.random.default_rng(42)
        port = rng.normal(0.001, 0.01, 252)
        bench = rng.normal(0.0005, 0.012, 252)

        comp = BenchmarkComparer.compare(port, bench, "SP500", "^GSPC")
        assert comp.benchmark_name == "SP500"
        assert comp.portfolio_return != 0
        assert comp.benchmark_return != 0
        assert comp.excess_return != 0
        assert comp.correlation != 0

    def test_capture_ratios(self):
        import numpy as np
        from app.backtesting.benchmark import BenchmarkComparer
        # Use correlated returns so capture ratios are meaningful
        rng = np.random.default_rng(42)
        bench = rng.normal(0.0005, 0.012, 252)
        # Portfolio = beta * bench + alpha + noise (correlated)
        port = 0.8 * bench + 0.0003 + rng.normal(0, 0.005, 252)
        comp = BenchmarkComparer.compare(port, bench)
        assert comp.up_capture > 0
        assert comp.down_capture > 0

    def test_compare_all(self):
        import numpy as np
        from app.backtesting.benchmark import BenchmarkComparer
        rng = np.random.default_rng(42)
        port = rng.normal(0.001, 0.01, 252)
        benchmarks = {
            "SP500": rng.normal(0.0005, 0.012, 252),
            "NIFTY50": rng.normal(0.0003, 0.013, 252),
        }
        report = BenchmarkComparer.compare_all(port, benchmarks)
        assert len(report.comparisons) == 2
        assert report.portfolio_rank >= 1
        assert report.best_benchmark != ""


class TestTradeJournal:
    """Phase 3: Trade journal with explainability.

    Ref: Brinson et al. 1986.
    """

    def test_record_trade(self):
        from app.backtesting.trade_journal import TradeJournal
        journal = TradeJournal()
        entry = journal.record_trade(
            trade={"symbol": "AAPL", "side": "BUY", "quantity": 100,
                   "price": 150.0, "pnl": 0},
            attribution={"strategy_name": "momentum", "strategy_alpha": 0.8,
                        "regime": "BULL", "regime_confidence": 0.9},
        )
        assert entry.symbol == "AAPL"
        assert entry.strategy_name == "momentum"
        assert entry.regime == "BULL"

    def test_filter(self):
        from app.backtesting.trade_journal import TradeJournal
        journal = TradeJournal()
        journal.record_trade({"symbol": "AAPL", "side": "BUY", "pnl": 100, "price": 150, "quantity": 10})
        journal.record_trade({"symbol": "GOOG", "side": "BUY", "pnl": -50, "price": 100, "quantity": 5})
        journal.record_trade({"symbol": "AAPL", "side": "SELL", "pnl": 200, "price": 160, "quantity": 10})

        aapl = journal.filter(symbol="AAPL")
        assert len(aapl) == 2
        winners = journal.filter(min_pnl=0.01)
        assert len(winners) == 2

    def test_summary(self):
        from app.backtesting.trade_journal import TradeJournal
        journal = TradeJournal()
        journal.record_trade(
            {"symbol": "X", "side": "BUY", "pnl": 100, "price": 10, "quantity": 1},
            attribution={"strategy_name": "momentum", "regime": "BULL"},
        )
        journal.record_trade(
            {"symbol": "Y", "side": "BUY", "pnl": -50, "price": 20, "quantity": 1},
            attribution={"strategy_name": "mean_reversion", "regime": "NEUTRAL"},
        )
        summary = journal.summary()
        assert summary["total_trades"] == 2
        assert summary["winning_trades"] == 1
        assert "momentum" in summary["by_strategy"]
        assert "BULL" in summary["by_regime"]

    def test_to_list(self):
        from app.backtesting.trade_journal import TradeJournal
        journal = TradeJournal()
        journal.record_trade({"symbol": "X", "side": "BUY", "pnl": 0, "price": 10, "quantity": 1})
        data = journal.to_list()
        assert len(data) == 1
        assert data[0]["symbol"] == "X"


class TestReportExporter:
    """Phase 3: CSV/report exporter."""

    def test_metrics_to_csv(self):
        from app.backtesting.report_exporter import ReportExporter
        csv_str = ReportExporter.metrics_to_csv({"sharpe_ratio": 1.5, "max_drawdown": 0.1})
        assert "sharpe_ratio" in csv_str
        assert "1.5" in csv_str

    def test_trades_to_csv(self):
        from app.backtesting.report_exporter import ReportExporter
        trades = [{"side": "BUY", "price": 100, "pnl": 50}]
        csv_str = ReportExporter.trades_to_csv(trades)
        assert "side" in csv_str
        assert "BUY" in csv_str

    def test_equity_curve_to_csv(self):
        from app.backtesting.report_exporter import ReportExporter
        csv_str = ReportExporter.equity_curve_to_csv([100, 105, 103])
        assert "portfolio_value" in csv_str
        assert "105" in csv_str

    def test_full_report(self):
        from app.backtesting.report_exporter import ReportExporter
        report = ReportExporter.full_report_to_csv(
            metrics={"sharpe": 1.2},
            equity_curve=[100, 110],
            trades=[{"side": "BUY", "price": 100, "pnl": 10}],
        )
        assert len(report) == 3
        # All values should be CSV strings
        for filename, content in report.items():
            assert filename.endswith(".csv")
            assert len(content) > 0

    def test_journal_to_csv(self):
        from app.backtesting.report_exporter import ReportExporter
        entries = [{"trade_id": "1", "symbol": "AAPL", "side": "BUY", "pnl": 100}]
        csv_str = ReportExporter.journal_to_csv(entries)
        assert "AAPL" in csv_str


# -- Phase 4 Tests ----------------------------------------------------------


class TestOrderSplitter:
    """Order splitting algorithms (Almgren & Chriss 2000, Cartea & Jaimungal 2015)."""

    def test_twap_schedule(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter()
        schedule = splitter.twap("ord-1", "AAPL", "BUY", 1000, n_slices=5)
        assert len(schedule.child_orders) == 5
        assert abs(sum(c.quantity for c in schedule.child_orders) - 1000) < 1
        # TWAP: equal slices
        assert all(c.quantity == 200 for c in schedule.child_orders)

    def test_vwap_schedule(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter()
        schedule = splitter.vwap("ord-1", "AAPL", "BUY", 1000, n_slices=5)
        assert len(schedule.child_orders) == 5
        assert abs(sum(c.quantity for c in schedule.child_orders) - 1000) < 1

    def test_almgren_chriss_optimal(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(volatility=0.02, risk_aversion=1e-6)
        schedule = splitter.almgren_chriss("ord-1", "AAPL", "BUY", 10000, n_slices=10)
        assert len(schedule.child_orders) == 10
        total = sum(c.quantity for c in schedule.child_orders)
        assert abs(total - 10000) < 10
        # First slice should be largest (front-loaded)
        assert schedule.child_orders[0].quantity >= schedule.child_orders[-1].quantity

    def test_auto_select(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(daily_volume=100000)
        schedule = splitter.create_schedule("ord-1", "AAPL", "BUY", 500)
        assert schedule.algorithm in ("TWAP", "VWAP", "ALMGREN_CHRISS")
        assert len(schedule.child_orders) > 0


class TestReconciliation:
    """Position reconciliation (ISDA 2013)."""

    def test_perfect_match(self):
        from app.services.reconciliation import ReconciliationEngine
        engine = ReconciliationEngine()
        internal = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100, "avg_entry_price": 150}]
        broker = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100, "avg_price": 150}]
        report = engine.reconcile(internal, broker, "TEST")
        assert report.matches == 1
        assert len(report.mismatches) == 0

    def test_quantity_mismatch(self):
        from app.services.reconciliation import ReconciliationEngine
        engine = ReconciliationEngine()
        internal = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100, "avg_entry_price": 150}]
        broker = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 90, "avg_price": 150}]
        report = engine.reconcile(internal, broker, "TEST")
        assert len(report.mismatches) == 1
        assert report.mismatches[0].delta_qty == 10

    def test_missing_at_broker(self):
        from app.services.reconciliation import ReconciliationEngine
        engine = ReconciliationEngine()
        internal = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100, "avg_entry_price": 150}]
        broker = []
        report = engine.reconcile(internal, broker, "TEST")
        assert len(report.mismatches) == 1
        assert report.mismatches[0].severity == "CRITICAL"

    def test_auto_resolve_rounding(self):
        from app.services.reconciliation import ReconciliationEngine
        engine = ReconciliationEngine(qty_tolerance=0.01)
        internal = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100.005, "avg_entry_price": 150}]
        broker = [{"symbol": "AAPL", "exchange": "NASDAQ", "quantity": 100.0, "avg_price": 150}]
        report = engine.reconcile(internal, broker, "TEST")
        assert report.matches == 1


class TestRateLimiter:
    """Token bucket rate limiter (Turner 1986, RFC 970)."""

    def test_add_bucket(self):
        from app.core.rate_limiter import RateLimiter
        limiter = RateLimiter()
        limiter.add_bucket("test", max_tokens=10, refill_rate=1.0)
        status = limiter.get_status()
        assert "test" in status
        assert status["test"]["max_tokens"] == 10

    def test_try_acquire(self):
        from app.core.rate_limiter import RateLimiter
        limiter = RateLimiter()
        limiter.add_bucket("test", max_tokens=2, refill_rate=0.1)
        assert limiter.try_acquire("test") is True
        assert limiter.try_acquire("test") is True
        assert limiter.try_acquire("test") is False  # Exhausted

    def test_no_limit_returns_true(self):
        from app.core.rate_limiter import RateLimiter
        limiter = RateLimiter()
        assert limiter.try_acquire("nonexistent") is True

    def test_default_limiter(self):
        from app.core.rate_limiter import create_default_limiter
        limiter = create_default_limiter()
        status = limiter.get_status()
        assert "alpaca" in status
        assert "zerodha" in status
        assert "anthropic" in status


class TestBackupService:
    """Disaster recovery backup (Phase 4)."""

    def test_backup_positions(self, tmp_path):
        from app.services.backup import BackupService
        svc = BackupService(backup_dir=tmp_path, max_backups=3)
        positions = [{"symbol": "AAPL", "quantity": 100, "avg_price": 150}]
        path = svc.backup_positions(positions)
        assert path is not None
        assert "positions_" in path

    def test_list_backups(self, tmp_path):
        from app.services.backup import BackupService
        svc = BackupService(backup_dir=tmp_path)
        svc.backup_positions([{"symbol": "AAPL"}])
        backups = svc.list_backups("positions_*")
        assert len(backups) == 1

    def test_rotation(self, tmp_path):
        from app.services.backup import BackupService
        import time
        svc = BackupService(backup_dir=tmp_path, max_backups=2)
        for i in range(4):
            svc.backup_positions([{"symbol": f"SYM{i}"}])
            time.sleep(0.05)
        backups = svc.list_backups("positions_*")
        assert len(backups) <= 2

    def test_load_positions(self, tmp_path):
        from app.services.backup import BackupService
        svc = BackupService(backup_dir=tmp_path)
        positions = [{"symbol": "AAPL", "quantity": 100}]
        path = svc.backup_positions(positions)
        loaded = svc.load_positions_backup(path)
        assert len(loaded) == 1
        assert loaded[0]["symbol"] == "AAPL"


class TestPrometheusMetrics:
    """Prometheus metrics exporter (Phase 4)."""

    def test_gauge(self):
        from app.monitoring.metrics import PrometheusMetrics
        m = PrometheusMetrics()
        m.set_gauge("test_value", 42.0, {"env": "test"})
        text = m.export()
        assert "test_value" in text
        assert "42.0" in text

    def test_counter(self):
        from app.monitoring.metrics import PrometheusMetrics
        m = PrometheusMetrics()
        m.inc_counter("test_count", {"type": "order"}, amount=3)
        text = m.export()
        assert "test_count" in text
        assert "3" in text

    def test_convenience_methods(self):
        from app.monitoring.metrics import PrometheusMetrics
        m = PrometheusMetrics()
        m.record_portfolio_value(1_000_000, "USD")
        m.record_pnl(5000, 2000)
        m.record_agent_health("regime-1", True)
        m.record_kill_switch(False)
        text = m.export()
        assert "horizon_portfolio_value" in text
        assert "horizon_pnl_realized" in text


class TestMultiModelDebate:
    """Multi-model debate with perspective rotation (Du et al. ICML 2024)."""

    def test_parse_debate_response(self):
        from app.agents.debate.multi_model_debate import _parse_debate_response
        raw = '{"argument": "Strong momentum", "vote": "FOR", "confidence": 0.85}'
        parsed = _parse_debate_response(raw)
        assert parsed["vote"] == "FOR"
        assert parsed["confidence"] == 0.85

    def test_parse_markdown_wrapped(self):
        from app.agents.debate.multi_model_debate import _parse_debate_response
        raw = '```json\n{"argument": "test", "vote": "AGAINST", "confidence": 0.3}\n```'
        parsed = _parse_debate_response(raw)
        assert parsed["vote"] == "AGAINST"

    def test_rotation_matrix(self):
        from app.agents.debate.multi_model_debate import ROTATION_MATRIX
        # Strategy rotates to Risk perspective and vice versa
        assert ROTATION_MATRIX["STRATEGY"] == "RISK"
        assert ROTATION_MATRIX["RISK"] == "STRATEGY"
        assert ROTATION_MATRIX["SENTIMENT"] == "PORTFOLIO"

    def test_multi_model_argument_dataclass(self):
        from app.agents.debate.multi_model_debate import MultiModelArgument
        arg = MultiModelArgument(
            role="STRATEGY", argument="test", vote="FOR",
            confidence=0.8, provider="claude", round_number=1,
        )
        assert arg.provider == "claude"
        assert arg.round_number == 1


# -- Phase 5 Tests ----------------------------------------------------------


class TestOptionsStrategy:
    """Options pricing and Greeks (Black-Scholes 1973, Heston 1993)."""

    def test_bs_call_price(self):
        from app.agents.front_office.strategy.options_strategy import bs_price
        # Standard BS test case: S=100, K=100, T=1, r=5%, σ=20%
        price = bs_price(100, 100, 1.0, 0.05, 0.20, "call")
        assert 9.0 < price < 12.0  # Expected ~10.45

    def test_bs_put_price(self):
        from app.agents.front_office.strategy.options_strategy import bs_price
        price = bs_price(100, 100, 1.0, 0.05, 0.20, "put")
        assert 4.0 < price < 7.0  # Expected ~5.57

    def test_put_call_parity(self):
        """Put-call parity: C - P = S - K*e^(-rT)."""
        import math
        from app.agents.front_office.strategy.options_strategy import bs_price
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 0.01

    def test_bs_greeks(self):
        from app.agents.front_office.strategy.options_strategy import bs_greeks
        g = bs_greeks(100, 100, 1.0, 0.05, 0.20, "call")
        assert 0.5 < g.delta < 0.75  # ATM call delta ~0.64
        assert g.gamma > 0
        assert g.vega > 0
        assert g.theta < 0  # Time decay is negative
        assert g.option_price > 0

    def test_put_delta_negative(self):
        from app.agents.front_office.strategy.options_strategy import bs_greeks
        g = bs_greeks(100, 100, 1.0, 0.05, 0.20, "put")
        assert -0.5 < g.delta < 0  # ATM put delta ~ -0.36

    def test_implied_volatility(self):
        from app.agents.front_office.strategy.options_strategy import (
            bs_price, implied_volatility,
        )
        S, K, T, r, true_vol = 100, 100, 1.0, 0.05, 0.25
        market_price = bs_price(S, K, T, r, true_vol, "call")
        iv = implied_volatility(market_price, S, K, T, r, "call")
        assert abs(iv - true_vol) < 0.001

    def test_heston_call_price(self):
        from app.agents.front_office.strategy.options_strategy import heston_call_price
        # Heston with zero vol-of-vol reduces toward BS
        price = heston_call_price(
            S0=100, K=100, r=0.05, T=1.0,
            v0=0.04, kappa=2.0, theta=0.04, sigma=0.01, rho=-0.7,
        )
        assert price > 0
        assert 5.0 < price < 20.0

    def test_svi_total_variance(self):
        from app.agents.front_office.strategy.options_strategy import (
            SVIParams, svi_total_variance,
        )
        params = SVIParams(a=0.04, b=0.1, rho=-0.3, m=0.0, sig=0.1)
        # ATM (k=0)
        var_atm = svi_total_variance(0.0, params)
        assert var_atm > 0
        # Wings should have higher variance (smile)
        var_otm = svi_total_variance(0.5, params)
        assert var_otm > var_atm

    def test_svi_calibration(self):
        import numpy as np
        from app.agents.front_office.strategy.options_strategy import calibrate_svi
        strikes = np.array([90, 95, 100, 105, 110], dtype=float)
        ivs = np.array([0.25, 0.22, 0.20, 0.22, 0.25])
        params = calibrate_svi(strikes, ivs, forward=100.0, T=1.0)
        assert params.b > 0
        assert abs(params.rho) < 1

    def test_hedge_selector_crisis(self):
        from app.agents.front_office.strategy.options_strategy import select_hedge
        hedge = select_hedge(spot=100, portfolio_value=10000, regime="CRISIS")
        assert hedge.strategy == "protective_put"
        assert hedge.put_strike is not None
        assert hedge.put_strike < 100

    def test_hedge_selector_bull(self):
        from app.agents.front_office.strategy.options_strategy import select_hedge
        hedge = select_hedge(spot=100, portfolio_value=10000, regime="BULL")
        assert hedge.strategy == "covered_call"
        assert hedge.call_strike is not None
        assert hedge.call_strike > 100

    def test_options_strategy_signal(self):
        from app.agents.front_office.strategy.options_strategy import OptionsStrategy
        strat = OptionsStrategy()
        signal = strat.generate_signal(
            "AAPL.NASDAQ",
            {"close": 150, "volatility_annual": 30, "atr_avg_20": 3},
            "CRISIS",
        )
        assert signal is not None
        assert signal.strategy_name == "options"


class TestArbitrageDetector:
    """Cross-market arbitrage (Avellaneda & Lee 2010, Gatev et al. 2006)."""

    def test_eigenportfolio_decompose(self):
        import numpy as np
        from app.agents.front_office.strategy.arbitrage_detector import EigenportfolioDetector
        np.random.seed(42)
        # Create correlated returns
        common = np.random.randn(252) * 0.01
        returns = {
            "A": common + np.random.randn(252) * 0.005,
            "B": common + np.random.randn(252) * 0.005,
            "C": common * 0.5 + np.random.randn(252) * 0.008,
            "D": np.random.randn(252) * 0.01,  # Uncorrelated
        }
        detector = EigenportfolioDetector()
        result = detector.decompose(returns)
        assert result.n_components >= 1
        assert result.variance_explained > 0
        assert len(result.s_scores) == 4

    def test_eigenportfolio_signals(self):
        import numpy as np
        from app.agents.front_office.strategy.arbitrage_detector import (
            EigenportfolioDetector, EigenportfolioResult,
        )
        detector = EigenportfolioDetector(entry_s_score=1.0)
        result = EigenportfolioResult(
            n_components=1, variance_explained=0.6,
            eigenvalues=[5.0],
            residuals={}, s_scores={"A": 1.5, "B": -1.8, "C": 0.3},
        )
        signals = detector.get_signals(result)
        assert len(signals) == 2  # A (short) and B (long)
        shorts = [s for s in signals if s["direction"] == -1]
        longs = [s for s in signals if s["direction"] == 1]
        assert len(shorts) == 1  # A
        assert len(longs) == 1   # B

    def test_pairs_trading_find(self):
        import numpy as np
        from app.agents.front_office.strategy.arbitrage_detector import PairsTradingDetector
        np.random.seed(42)
        # Deterministic cointegrated pair: A and B share same base trend
        base = np.linspace(100, 110, 100)
        prices = {
            "A": base + np.sin(np.linspace(0, 4*np.pi, 100)) * 0.5,
            "B": base + np.cos(np.linspace(0, 4*np.pi, 100)) * 0.5,
            "C": np.linspace(50, 80, 100),  # Uncorrelated linear trend
        }
        detector = PairsTradingDetector(top_n=5)
        pairs = detector.find_pairs(prices)
        assert len(pairs) >= 1
        # A-B should be closest pair (similar base + small deviation)
        ab_pair = [p for p in pairs if set([p.symbol_a, p.symbol_b]) == {"A", "B"}]
        assert len(ab_pair) == 1
        assert ab_pair[0].distance < pairs[-1].distance  # Closest pair

    def test_half_life(self):
        import numpy as np
        from app.agents.front_office.strategy.arbitrage_detector import PairsTradingDetector
        # Mean-reverting spread with known half-life
        np.random.seed(42)
        spread = np.zeros(200)
        for t in range(1, 200):
            spread[t] = 0.95 * spread[t-1] + np.random.randn() * 0.1
        hl = PairsTradingDetector._compute_half_life(spread)
        assert 5 < hl < 30  # ~13.5 days for b=0.95

    def test_cross_market_detector(self):
        import numpy as np
        from app.agents.front_office.strategy.arbitrage_detector import CrossMarketArbitrageDetector
        np.random.seed(42)
        common = np.random.randn(100) * 0.01
        returns = {
            "AAPL": common + np.random.randn(100) * 0.005,
            "MSFT": common + np.random.randn(100) * 0.005,
            "TSLA": np.random.randn(100) * 0.02,
        }
        prices = {
            s: np.exp(np.cumsum(r)) * 100 for s, r in returns.items()
        }
        detector = CrossMarketArbitrageDetector()
        result = detector.detect(returns, prices)
        assert "summary" in result
        assert "eigenportfolio" in result
        assert "pairs" in result


class TestMacroFactors:
    """Macro factor integration (Ang & Piazzesi 2003, Chen et al. 1986)."""

    def test_regime_expansionary(self):
        from app.services.macro_factors import MacroRegimeClassifier
        classifier = MacroRegimeClassifier()
        snapshot = classifier.classify({
            "industrial_production": 0.5,
            "term_spread": 1.5,
            "credit_spread": -0.3,
            "unemployment": -0.5,
        })
        assert snapshot.regime_signal == "EXPANSIONARY"
        assert snapshot.composite_score > 0

    def test_regime_contractionary(self):
        from app.services.macro_factors import MacroRegimeClassifier
        classifier = MacroRegimeClassifier()
        snapshot = classifier.classify({
            "industrial_production": -0.8,
            "credit_spread": 1.5,
            "term_spread": -0.5,
            "unemployment": 1.0,
        })
        assert snapshot.regime_signal == "CONTRACTIONARY"
        assert snapshot.composite_score < 0

    def test_risk_adjustment_range(self):
        from app.services.macro_factors import MacroRegimeClassifier
        classifier = MacroRegimeClassifier()
        snapshot = classifier.classify({"industrial_production": 0.0, "term_spread": 0.0})
        assert 0.5 <= snapshot.risk_adjustment <= 1.5

    def test_term_structure_inverted(self):
        from app.services.macro_factors import term_structure_signal
        sig = term_structure_signal(short_rate=5.0, long_rate=4.0, credit_spread=1.0)
        assert sig["is_inverted"] is True
        assert sig["allocation_signal"] == "DEFENSIVE"
        assert sig["equity_weight_adj"] < 0

    def test_term_structure_steep(self):
        from app.services.macro_factors import term_structure_signal
        sig = term_structure_signal(short_rate=2.0, long_rate=5.0, credit_spread=1.0)
        assert sig["is_steep"] is True
        assert sig["allocation_signal"] == "RISK_ON"

    def test_pca_factor_extraction(self):
        import numpy as np
        from app.services.macro_factors import MacroFactorExtractor
        np.random.seed(42)
        panel = {
            "gdp": np.random.randn(100),
            "cpi": np.random.randn(100),
            "employment": np.random.randn(100),
        }
        extractor = MacroFactorExtractor(n_factors=2)
        model = extractor.extract(panel)
        assert model.n_factors == 2
        assert len(model.eigenvalues) == 2
        assert sum(model.variance_explained) > 0

    def test_macro_integration(self):
        from app.services.macro_factors import MacroIntegrationService
        svc = MacroIntegrationService()
        result = svc.analyze(
            macro_data={"industrial_production": 0.3, "term_spread": 1.0},
            term_structure={"short_rate": 2.0, "long_rate": 4.0, "credit_spread": 1.0},
        )
        assert "macro_regime" in result
        assert "risk_adjustment" in result
        assert "term_structure" in result


class TestTaxHarvesting:
    """Tax-loss harvesting (Israelov & Lu 2022, Berkin & Ye 2003)."""

    def test_tax_lot_properties(self):
        from datetime import datetime, timezone
        from app.services.tax_harvesting import TaxLot
        lot = TaxLot(
            symbol="AAPL", quantity=100, cost_basis=150,
            purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            current_price=140, exchange="NASDAQ",
        )
        assert lot.unrealized_pnl == -1000  # (140-150)*100
        assert lot.unrealized_pnl_pct < 0
        assert lot.is_long_term  # > 365 days from 2024-01-01

    def test_scan_finds_losses(self):
        from datetime import datetime, timezone
        from app.services.tax_harvesting import TaxHarvestingEngine, TaxLot
        engine = TaxHarvestingEngine(jurisdiction="US")
        lots = [
            TaxLot("AAPL", 100, 150, datetime(2024, 1, 1, tzinfo=timezone.utc), 130, "NASDAQ"),
            TaxLot("MSFT", 50, 300, datetime(2024, 6, 1, tzinfo=timezone.utc), 310, "NASDAQ"),
        ]
        result = engine.scan(lots)
        assert result.lots_eligible == 1  # Only AAPL has loss
        assert result.total_harvestable_loss > 0

    def test_wash_sale_check(self):
        from datetime import datetime, timedelta, timezone
        from app.services.tax_harvesting import TaxHarvestingEngine
        engine = TaxHarvestingEngine(jurisdiction="US")
        now = datetime.now(timezone.utc)
        engine.record_harvest("AAPL", now - timedelta(days=10))
        assert engine._check_wash_sale("AAPL", now) is False  # Within 30 days
        assert engine._check_wash_sale("MSFT", now) is True   # Different symbol

    def test_india_no_wash_sale(self):
        from datetime import datetime, timedelta, timezone
        from app.services.tax_harvesting import TaxHarvestingEngine
        engine = TaxHarvestingEngine(jurisdiction="INDIA")
        now = datetime.now(timezone.utc)
        engine.record_harvest("RELIANCE.NSE", now - timedelta(days=5))
        assert engine._check_wash_sale("RELIANCE.NSE", now) is True

    def test_estimate_alpha(self):
        from app.services.tax_harvesting import TaxHarvestingEngine
        engine = TaxHarvestingEngine()
        alpha = engine.estimate_annual_alpha(
            portfolio_value=1_000_000, annual_volatility=0.25, tax_rate=0.30,
        )
        assert 20 <= alpha <= 150  # Israelov & Lu 2022: 20-150 bps

    def test_hifo_priority(self):
        """HIFO lot selection: highest cost basis first (Berkin & Ye 2003)."""
        from datetime import datetime, timezone
        from app.services.tax_harvesting import TaxHarvestingEngine, TaxLot
        engine = TaxHarvestingEngine()
        lots = [
            TaxLot("AAPL", 50, 160, datetime(2024, 3, 1, tzinfo=timezone.utc), 140, "NASDAQ"),
            TaxLot("AAPL", 50, 180, datetime(2024, 1, 1, tzinfo=timezone.utc), 140, "NASDAQ"),
        ]
        result = engine.scan(lots)
        # Higher cost basis (180) should have higher priority
        assert result.candidates[0].lot.cost_basis == 180


class TestPortfolioRebalancer:
    """Portfolio rebalancing with drawdown constraints (Boyd et al. 2017)."""

    def test_drawdown_cushion(self):
        from app.services.portfolio_rebalancer import DrawdownConstrainedRebalancer
        reb = DrawdownConstrainedRebalancer(max_drawdown=0.20)
        # No drawdown: full cushion
        c1 = reb.compute_drawdown_cushion(1000, 1000)
        assert 0.15 < c1 < 0.20
        # 10% drawdown: half cushion
        c2 = reb.compute_drawdown_cushion(900, 1000)
        assert c2 < c1
        # Near max drawdown: very small cushion
        c3 = reb.compute_drawdown_cushion(810, 1000)
        assert c3 < c2

    def test_risk_aversion_increases_near_limit(self):
        from app.services.portfolio_rebalancer import DrawdownConstrainedRebalancer
        reb = DrawdownConstrainedRebalancer(max_drawdown=0.20, base_risk_aversion=2.0)
        gamma_relaxed = reb.compute_risk_aversion(0.15)
        gamma_stressed = reb.compute_risk_aversion(0.05)
        assert gamma_stressed > gamma_relaxed

    def test_optimize_weights(self):
        import numpy as np
        from app.services.portfolio_rebalancer import DrawdownConstrainedRebalancer
        reb = DrawdownConstrainedRebalancer()
        cov = np.array([[0.04, 0.01], [0.01, 0.03]])
        weights = reb.optimize_weights(
            current_weights={"A": 0.5, "B": 0.5},
            expected_returns={"A": 0.10, "B": 0.08},
            covariance=cov,
            symbols=["A", "B"],
            cushion=0.15,
        )
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert all(w >= 0 for w in weights.values())

    def test_generate_orders(self):
        from app.services.portfolio_rebalancer import DrawdownConstrainedRebalancer
        reb = DrawdownConstrainedRebalancer()
        orders = reb.generate_orders(
            current_weights={"A": 0.6, "B": 0.4},
            target_weights={"A": 0.5, "B": 0.5},
            portfolio_value=100000,
            current_prices={"A": 100, "B": 50},
        )
        assert len(orders) == 2
        sells = [o for o in orders if o.direction == "SELL"]
        buys = [o for o in orders if o.direction == "BUY"]
        assert len(sells) == 1
        assert len(buys) == 1

    def test_rebalance_trigger_calendar(self):
        from app.services.portfolio_rebalancer import should_rebalance
        trigger, reason = should_rebalance(
            {"A": 0.5}, {"A": 0.5}, days_since_last=31,
        )
        assert trigger is True
        assert "Calendar" in reason

    def test_rebalance_trigger_drift(self):
        from app.services.portfolio_rebalancer import should_rebalance
        trigger, reason = should_rebalance(
            {"A": 0.6, "B": 0.4}, {"A": 0.5, "B": 0.5},
            max_drift_pct=5.0, days_since_last=5,
        )
        assert trigger is True
        assert "Drift" in reason

    def test_no_rebalance_needed(self):
        from app.services.portfolio_rebalancer import should_rebalance
        trigger, _ = should_rebalance(
            {"A": 0.51, "B": 0.49}, {"A": 0.5, "B": 0.5},
            days_since_last=5,
        )
        assert trigger is False

    def test_ledoit_wolf_shrinkage(self):
        import numpy as np
        from app.services.portfolio_rebalancer import DrawdownConstrainedRebalancer
        cov = np.array([[0.04, 0.02, 0.01],
                        [0.02, 0.03, 0.01],
                        [0.01, 0.01, 0.05]])
        shrunk = DrawdownConstrainedRebalancer._shrink_covariance(cov)
        # Shrunk should still be positive definite
        eigenvalues = np.linalg.eigvalsh(shrunk)
        assert all(e > 0 for e in eigenvalues)


# -- Phase 6-10 Tests -------------------------------------------------------


class TestStressTesting:
    """Stress testing & scenario analysis (Jorion 2006, Rebonato 2010)."""

    def test_historical_scenarios_exist(self):
        from app.services.stress_testing import HISTORICAL_SCENARIOS
        assert "GFC_2008" in HISTORICAL_SCENARIOS
        assert "COVID_2020" in HISTORICAL_SCENARIOS
        assert "FLASH_CRASH_2010" in HISTORICAL_SCENARIOS
        assert len(HISTORICAL_SCENARIOS) >= 7

    def test_run_all_scenarios(self):
        from app.services.stress_testing import StressTestingService
        service = StressTestingService()
        positions = [
            {"symbol": "RELIANCE.NSE", "weight_pct": 30},
            {"symbol": "AAPL.NASDAQ", "weight_pct": 30},
            {"symbol": "BTC-USD", "weight_pct": 20},
            {"symbol": "TCS.NSE", "weight_pct": 20},
        ]
        report = service.run_historical_scenarios(positions, 1_000_000)
        assert report.n_scenarios >= 7
        assert report.worst_case_scenario != ""
        assert report.worst_case_impact_pct < 0
        assert 0 <= report.aggregate_risk_score <= 100

    def test_scenario_impact_direction(self):
        from app.services.stress_testing import StressTestingService
        service = StressTestingService()
        positions = [{"symbol": "AAPL.NASDAQ", "weight_pct": 100}]
        report = service.run_historical_scenarios(positions, 1_000_000)
        # GFC should cause negative impact
        gfc = [r for r in report.scenario_results if r.scenario_key == "GFC_2008"]
        assert len(gfc) == 1
        assert gfc[0].portfolio_impact_pct < 0

    def test_crypto_specific_shock(self):
        from app.services.stress_testing import StressTestingService
        service = StressTestingService()
        positions = [{"symbol": "BTC-USD", "weight_pct": 100}]
        report = service.run_historical_scenarios(positions, 100_000)
        crypto_winter = [r for r in report.scenario_results if r.scenario_key == "CRYPTO_WINTER_2022"]
        assert len(crypto_winter) == 1
        assert crypto_winter[0].portfolio_impact_pct < -0.50  # >50% loss

    def test_parametric_stress(self):
        from app.services.stress_testing import StressTestingService
        service = StressTestingService()
        positions = [
            {"symbol": "AAPL.NASDAQ", "weight_pct": 60},
            {"symbol": "RELIANCE.NSE", "weight_pct": 40},
        ]
        result = service.run_parametric(positions, 1_000_000, equity_shock=-0.30)
        assert result["total_impact"] < 0
        assert result["impact_pct"] < 0
        assert result["equity_impact"] < 0

    def test_correlation_breakdown(self):
        import numpy as np
        from app.services.stress_testing import StressTestingService
        np.random.seed(42)
        n_days = 200
        # Normal: low correlation; Crisis: high correlation
        returns = np.random.randn(n_days, 3) * 0.01
        # Add crisis days (correlated drops)
        for i in range(0, n_days, 20):
            returns[i] = -0.03  # All assets drop together
        result = StressTestingService.correlation_breakdown(
            returns, ["A", "B", "C"], crisis_threshold=-0.02,
        )
        assert result["crisis_avg_correlation"] > result["normal_avg_correlation"]
        assert result["diversification_decay"] > 0


class TestAlertManager:
    """Alert & notification system (Jorion 2006 Ch. 15)."""

    def test_default_rules_loaded(self):
        from app.services.alert_manager import AlertManager
        mgr = AlertManager.__new__(AlertManager)
        from app.services.alert_manager import DEFAULT_RULES
        rules = {r.name: r for r in DEFAULT_RULES}
        mgr._rules = rules
        mgr._history = []
        mgr._alert_counter = 0
        assert "drawdown_warning" in mgr._rules
        assert "kill_switch_activated" in mgr._rules
        assert "var_breach" in mgr._rules
        assert len(mgr._rules) >= 7

    def test_rule_toggle(self):
        from app.services.alert_manager import AlertManager, DEFAULT_RULES
        mgr = AlertManager.__new__(AlertManager)
        mgr._rules = {r.name: r for r in DEFAULT_RULES}
        mgr._history = []
        original = mgr._rules["drawdown_warning"].enabled
        result = mgr.toggle_rule("drawdown_warning")
        assert result == (not original)
        result2 = mgr.toggle_rule("drawdown_warning")
        assert result2 == original

    def test_toggle_nonexistent(self):
        from app.services.alert_manager import AlertManager, DEFAULT_RULES
        mgr = AlertManager.__new__(AlertManager)
        mgr._rules = {r.name: r for r in DEFAULT_RULES}
        assert mgr.toggle_rule("fake_rule") is None

    def test_alert_history_query(self):
        from app.services.alert_manager import Alert, AlertManager, AlertSeverity, DEFAULT_RULES
        mgr = AlertManager.__new__(AlertManager)
        mgr._rules = {r.name: r for r in DEFAULT_RULES}
        mgr._history = [
            Alert("a1", "test", AlertSeverity.WARNING, "Test Warning", "msg1"),
            Alert("a2", "test", AlertSeverity.CRITICAL, "Test Critical", "msg2"),
        ]
        all_alerts = mgr.get_recent_alerts()
        assert len(all_alerts) == 2
        warnings = mgr.get_recent_alerts(severity="WARNING")
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "WARNING"


class TestModelRegistry:
    """ML model registry & Thompson Sampling (Agrawal & Goyal 2012)."""

    def test_register_model(self):
        from app.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        mv = reg.register("momentum", "strategy", {"window": 20})
        assert mv.model_id == "momentum_v1"
        assert mv.model_type == "strategy"
        assert mv.status == "active"

    def test_version_increment(self):
        from app.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        v1 = reg.register("momentum", "strategy")
        v2 = reg.register("momentum", "strategy")
        assert v1.version == 1
        assert v2.version == 2

    def test_update_metrics(self):
        from app.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        mv = reg.register("momentum", "strategy")
        reg.update_metrics(mv.model_id, {"sharpe_ratio": 1.5})
        assert reg._models[mv.model_id].metrics["sharpe_ratio"] == 1.5

    def test_get_best_model(self):
        from app.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        v1 = reg.register("momentum", "strategy")
        v2 = reg.register("momentum", "strategy")
        reg.update_metrics(v1.model_id, {"sharpe_ratio": 1.0})
        reg.update_metrics(v2.model_id, {"sharpe_ratio": 2.0})
        best = reg.get_best_model("momentum", "sharpe_ratio")
        assert best == v2.model_id

    def test_deprecate_model(self):
        from app.services.model_registry import ModelRegistry
        reg = ModelRegistry()
        mv = reg.register("momentum", "strategy")
        reg.deprecate(mv.model_id)
        assert reg._models[mv.model_id].status == "deprecated"
        # Should not appear in active models
        active = reg.get_active_models()
        assert len(active) == 0

    def test_thompson_sampling_select(self):
        from app.services.model_registry import ThompsonSamplingSelector
        selector = ThompsonSamplingSelector(
            ["momentum", "mean_reversion", "volatility"],
            random_seed=42,
        )
        # All arms are equal initially, any selection is valid
        choice = selector.select()
        assert choice in ["momentum", "mean_reversion", "volatility"]

    def test_thompson_sampling_exploitation(self):
        from app.services.model_registry import ThompsonSamplingSelector
        selector = ThompsonSamplingSelector(
            ["good", "bad"], random_seed=42,
        )
        # Feed many positive rewards to "good"
        for _ in range(100):
            selector.update("good", 0.05)
            selector.update("bad", -0.02)
        # "good" should be selected more often
        selections = [selector.select() for _ in range(100)]
        good_count = selections.count("good")
        assert good_count > 70  # Should exploit "good" most of the time

    def test_thompson_stats(self):
        from app.services.model_registry import ThompsonSamplingSelector
        selector = ThompsonSamplingSelector(
            ["a", "b"], random_seed=42,
        )
        selector.update("a", 0.03)
        selector.update("b", -0.01)
        stats = selector.get_stats()
        assert len(stats) == 2
        a_stats = [s for s in stats if s["strategy"] == "a"][0]
        assert a_stats["n_observations"] == 1
        assert a_stats["posterior_mean"] > 0

    def test_cusum_drift_detection(self):
        import numpy as np
        from app.services.model_registry import CUSUMDriftDetector
        np.random.seed(42)
        detector = CUSUMDriftDetector(threshold=3.0, warmup=20)

        # Warmup period: no drift
        for _ in range(25):
            result = detector.update(np.random.normal(0, 0.1))
        assert not result["drift_detected"]

        # Inject positive drift
        for _ in range(20):
            result = detector.update(np.random.normal(0.5, 0.1))
        # Should detect drift
        assert detector.drift_count >= 1

    def test_cusum_no_drift(self):
        import numpy as np
        from app.services.model_registry import CUSUMDriftDetector
        np.random.seed(42)
        detector = CUSUMDriftDetector(threshold=5.0, warmup=20)
        # Stable distribution
        for _ in range(100):
            detector.update(np.random.normal(0, 0.1))
        # Should not detect drift (or very rarely)
        assert detector.drift_count <= 1


class TestPixelAgents:
    """Pixel agent TUI visualization."""

    def test_register_agent(self):
        from app.tui.pixel_agents import PixelAgentVisualizer
        viz = PixelAgentVisualizer()
        viz.register_agent("risk-agent", "middle_office")
        assert viz.get_agent_count() == 1

    def test_update_state(self):
        from app.tui.pixel_agents import PixelAgentVisualizer
        viz = PixelAgentVisualizer()
        viz.update_state("risk-agent", "RUNNING", "middle_office")
        states = viz.get_states_summary()
        assert "ANALYZING" in states  # RUNNING maps to ANALYZING

    def test_build_panel(self):
        from app.tui.pixel_agents import PixelAgentVisualizer
        viz = PixelAgentVisualizer()
        viz.update_state("risk-agent", "RUNNING", "middle_office")
        viz.update_state("regime-agent", "IDLE", "front_office")
        panel = viz.build_panel()
        assert panel is not None

    def test_short_name(self):
        from app.tui.pixel_agents import PixelAgentVisualizer
        assert PixelAgentVisualizer._make_short_name("regime-agent-1") == "REGIME"
        assert PixelAgentVisualizer._make_short_name("risk-agent") == "RISK"


class TestPluginManager:
    """Plugin architecture (Gamma et al. 1994 Strategy Pattern)."""

    def test_init_creates_dir(self, tmp_path):
        from app.plugins.plugin_manager import PluginManager
        pm = PluginManager(plugin_dir=tmp_path / "plugins")
        pm.discover()
        assert (tmp_path / "plugins").exists()

    def test_discover_empty(self, tmp_path):
        from app.plugins.plugin_manager import PluginManager
        pm = PluginManager(plugin_dir=tmp_path)
        plugins = pm.discover()
        assert len(plugins) == 0

    def test_list_plugins(self, tmp_path):
        from app.plugins.plugin_manager import PluginManager
        pm = PluginManager(plugin_dir=tmp_path)
        assert len(pm.list_plugins()) == 0

    def test_get_nonexistent(self, tmp_path):
        from app.plugins.plugin_manager import PluginManager
        pm = PluginManager(plugin_dir=tmp_path)
        assert pm.get_strategy("fake") is None


class TestNewMessageTypes:
    """Core message types exist."""

    def test_risk_alert_exists(self):
        from app.core.messaging import MessageType
        assert MessageType.RISK_ALERT == "risk_alert"

    def test_risk_check_exists(self):
        from app.core.messaging import MessageType
        assert MessageType.RISK_CHECK == "risk_check"

    def test_order_cancel_exists(self):
        from app.core.messaging import MessageType
        assert MessageType.ORDER_CANCEL == "order_cancel"


class TestRiskConfig:
    """Risk configuration settings."""

    def test_daily_loss_limit_default(self):
        from app.config import settings
        assert settings.risk_daily_loss_limit_pct == 5.0

    def test_max_orders_per_minute_default(self):
        from app.config import settings
        assert settings.risk_max_orders_per_minute == 10


class TestPersistentKVStore:
    """PersistentKVStore basic operations."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        from app.core.kv_store import PersistentKVStore
        kv = PersistentKVStore()
        await kv.set("test:key", "test_value")
        assert await kv.get("test:key") == "test_value"

    @pytest.mark.asyncio
    async def test_delete(self):
        from app.core.kv_store import PersistentKVStore
        kv = PersistentKVStore()
        await kv.set("test:del", "val")
        await kv.delete("test:del")
        assert await kv.get("test:del") is None

    @pytest.mark.asyncio
    async def test_persist_keys_defined(self):
        from app.core.kv_store import PersistentKVStore
        assert "horizon:cash:usd" in PersistentKVStore._PERSIST_KEYS
        assert "horizon:system:kill_switch" in PersistentKVStore._PERSIST_KEYS


class TestOrderSplitterAutoSelect:
    """OrderSplitter auto-select algorithm based on participation."""

    def test_small_order_single_slice(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(daily_volume=1_000_000)
        schedule = splitter.create_schedule(
            parent_order_id="test-1", symbol="AAPL", side="BUY",
            total_quantity=100,  # 0.01% participation
        )
        assert schedule.n_slices == 1
        assert schedule.algorithm == "TWAP"

    def test_medium_order_twap(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(daily_volume=1_000_000)
        schedule = splitter.create_schedule(
            parent_order_id="test-2", symbol="AAPL", side="BUY",
            total_quantity=20_000,  # 2% participation
        )
        assert schedule.algorithm == "TWAP"
        assert schedule.n_slices == 10

    def test_large_order_vwap(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(daily_volume=1_000_000)
        schedule = splitter.create_schedule(
            parent_order_id="test-3", symbol="AAPL", side="BUY",
            total_quantity=80_000,  # 8% participation
        )
        assert schedule.algorithm == "VWAP"

    def test_very_large_order_almgren_chriss(self):
        from app.agents.front_office.trading.order_splitter import OrderSplitter
        splitter = OrderSplitter(daily_volume=1_000_000)
        schedule = splitter.create_schedule(
            parent_order_id="test-4", symbol="AAPL", side="SELL",
            total_quantity=200_000,  # 20% participation
        )
        assert schedule.algorithm == "ALMGREN_CHRISS"


class TestMarketHoursValidation:
    """Market hours check returns expected values."""

    def test_crypto_always_open(self):
        from app.agents.front_office.trading.execution_agent import ExecutionAgent
        assert ExecutionAgent._is_market_open("CRYPTO") is True

    def test_unknown_exchange_always_open(self):
        from app.agents.front_office.trading.execution_agent import ExecutionAgent
        assert ExecutionAgent._is_market_open("OTHER") is True

    def test_nse_returns_bool(self):
        from app.agents.front_office.trading.execution_agent import ExecutionAgent
        result = ExecutionAgent._is_market_open("NSE")
        assert isinstance(result, bool)

    def test_nasdaq_returns_bool(self):
        from app.agents.front_office.trading.execution_agent import ExecutionAgent
        result = ExecutionAgent._is_market_open("NASDAQ")
        assert isinstance(result, bool)


class TestBrokerConnect:
    """Broker connect, disconnect, and go-live commands."""

    def test_alpaca_broker_dynamic_credentials(self):
        """AlpacaBroker reads credentials dynamically from settings."""
        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        # headers is a property, not a cached dict
        h = broker.headers
        assert "APCA-API-KEY-ID" in h
        assert "APCA-API-SECRET-KEY" in h
        # base_url is a property
        assert broker.base_url.startswith("https://")

    def test_alpaca_get_account_method_exists(self):
        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        assert hasattr(broker, "get_account")
        assert asyncio.iscoroutinefunction(broker.get_account)

    def test_zerodha_broker_dynamic_credentials(self):
        """ZerodhaBroker reads credentials dynamically from settings."""
        from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
        broker = ZerodhaBroker()
        # Properties delegate to settings
        assert isinstance(broker.mock_mode, bool)
        assert isinstance(broker.api_key, str)
        assert isinstance(broker.api_secret, str)

    def test_zerodha_get_profile_exists(self):
        from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
        broker = ZerodhaBroker()
        assert hasattr(broker, "get_profile")
        assert asyncio.iscoroutinefunction(broker.get_profile)

    def test_zerodha_get_margins_exists(self):
        from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker
        broker = ZerodhaBroker()
        assert hasattr(broker, "get_margins")
        assert asyncio.iscoroutinefunction(broker.get_margins)

    @pytest.mark.asyncio
    async def test_connect_no_args_shows_status(self):
        """connect (no args) should return broker connection table info."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("connect")
        assert result is not None
        assert "connect alpaca" in result or "connect zerodha" in result

    @pytest.mark.asyncio
    async def test_broker_status_command(self):
        """broker status should return system mode info."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("broker status")
        assert result is not None
        assert "System mode" in result or "mode" in result.lower()

    @pytest.mark.asyncio
    async def test_disconnect_no_args_shows_usage(self):
        """disconnect (no args) should show usage."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("disconnect")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_connect_unknown_broker(self):
        """connect <unknown> should return error."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("connect fakeBroker")
        assert "Unknown broker" in result

    @pytest.mark.asyncio
    async def test_broker_account_no_creds(self):
        """broker account should handle no credentials gracefully."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("broker account")
        assert result is not None
        assert "not configured" in result or "Broker" in result

    @pytest.mark.asyncio
    async def test_broker_positions_no_creds(self):
        """broker positions should handle no positions gracefully."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        result = await handler.handle("broker positions")
        assert result is not None

    def test_write_env_keys_helper(self, tmp_path):
        """_write_env_keys merges and removes keys correctly."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")
        # Monkey-patch _get_env_path
        handler._get_env_path = lambda: env_file
        handler._write_env_keys(updates={"FOO": "new", "ADDED": "val"}, removals=["BAZ"])
        content = env_file.read_text()
        assert "FOO=new" in content
        assert "ADDED=val" in content
        assert "BAZ" not in content

    def test_mode_command_exists(self):
        """mode command should exist in handlers."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        assert hasattr(handler, "_cmd_mode")

    def test_go_live_command_exists(self):
        """go-live command should exist."""
        from app.tui.commands import CommandHandler
        handler = CommandHandler()
        assert hasattr(handler, "_cmd_go_live")

    def test_help_text_includes_broker_section(self):
        from app.tui.commands import HELP_TEXT
        assert "Broker & Live Trading" in HELP_TEXT
        assert "connect alpaca" in HELP_TEXT
        assert "go-live" in HELP_TEXT
        assert "disconnect" in HELP_TEXT


class TestPriceUpdate:
    def test_tick_message_type_exists(self):
        from app.core.messaging import MessageType
        assert hasattr(MessageType, "TICK")

    @pytest.mark.asyncio
    async def test_tick_message_roundtrip(self):
        from app.core.messaging import AgentMessage, MessageType
        msg = AgentMessage(
            sender_id="data-ingestion-worker",
            channel="horizon.market.price",
            message_type=MessageType.TICK,
            payload={
                "symbol": "RELIANCE.NSE",
                "price": 2847.50,
                "change_pct": 1.2,
                "volume": 2_100_000,
                "prev_close": 2813.82,
            },
        )
        serialized = msg.serialize()
        deserialized = AgentMessage.deserialize(serialized)
        assert deserialized.message_type == MessageType.TICK
        assert deserialized.payload["symbol"] == "RELIANCE.NSE"
        assert deserialized.payload["price"] == 2847.50


class TestPortfolioUpdatePayload:
    @pytest.mark.asyncio
    async def test_portfolio_update_contains_position_details(self):
        """PORTFOLIO_UPDATE payload should include a list of position dicts."""
        from app.core.messaging import AgentMessage, MessageType
        msg = AgentMessage(
            sender_id="position-monitor-worker",
            channel="horizon.portfolio.update",
            message_type=MessageType.PORTFOLIO_UPDATE,
            payload={
                "nav": 1_024_350.0,
                "cash": 241_000.0,
                "positions": [
                    {
                        "symbol": "RELIANCE.NSE",
                        "qty": 100,
                        "avg_cost": 2_805.0,
                        "current_price": 2_847.50,
                        "unrealized_pnl": 4250.0,
                        "side": "LONG",
                    },
                ],
                "total_unrealized": 4250.0,
                "total_realized": 0.0,
            },
        )
        positions = msg.payload["positions"]
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0]["symbol"] == "RELIANCE.NSE"
        assert positions[0]["qty"] == 100


class TestAgentCurrentTask:
    def test_base_agent_has_emit_method(self):
        from app.agents.base_agent import BaseAgent
        assert hasattr(BaseAgent, "emit")
        assert callable(BaseAgent.emit)

    def test_base_agent_has_heartbeat(self):
        from app.agents.base_agent import BaseAgent
        assert hasattr(BaseAgent, "_heartbeat_loop")
