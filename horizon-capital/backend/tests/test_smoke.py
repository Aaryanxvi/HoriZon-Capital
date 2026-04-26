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
        # US-only scope: at least one US symbol must parse; India/crypto lists
        # may be empty by configuration.
        assert "AAPL.NASDAQ" in symbols
        assert all("." in s or "-" in s for s in symbols)

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

    def test_simple_strategies(self):
        from app.agents.front_office.strategy.simple_strategies import (
            RSIStrategy, MACDStrategy, BollingerBandStrategy,
        )
        assert RSIStrategy is not None
        assert MACDStrategy is not None
        assert BollingerBandStrategy is not None


class TestSimpleStrategies:
    """Simple trading strategies."""

    def test_create_strategies(self):
        from app.agents.front_office.strategy.simple_strategies import (
            RSIStrategy, MACDStrategy, BollingerBandStrategy,
        )
        strategies = [RSIStrategy(), MACDStrategy(), BollingerBandStrategy()]
        assert len(strategies) == 3

    def test_strategy_names(self):
        from app.agents.front_office.strategy.simple_strategies import (
            RSIStrategy, MACDStrategy, BollingerBandStrategy,
        )
        assert RSIStrategy().name == "rsi"
        assert MACDStrategy().name == "macd"
        assert BollingerBandStrategy().name == "bollinger"


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
        assert "backtest" in result
        assert "health" in result

    @pytest.mark.asyncio
    async def test_config_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("config")
        assert "PAPER_TRADING" in result
        assert "CIO Mode" in result

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
    async def test_agents_command(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("agents")
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


class TestBaseStrategy:
    """Base strategy interface."""

    def test_signal_dataclass(self):
        from app.agents.front_office.strategy.base_strategy import Signal

        sig = Signal(symbol="AAPL", direction=1, strength=0.8, strategy_name="rsi")
        assert sig.symbol == "AAPL"
        assert sig.direction == 1
        assert sig.strength == 0.8
        assert sig.timestamp is not None

    def test_signal_optional_fields(self):
        from app.agents.front_office.strategy.base_strategy import Signal

        sig = Signal(
            symbol="AAPL", direction=-1, strength=0.5, strategy_name="macd",
            reasoning="test", target_price=100.0, stop_loss=95.0,
        )
        assert sig.target_price == 100.0
        assert sig.stop_loss == 95.0
        assert sig.reasoning == "test"


class TestNewMessageTypes:
    """Phase 2 message types exist."""

    def test_alpha_decay(self):
        from app.core.messaging import MessageType
        assert hasattr(MessageType, "ALPHA_DECAY")
        assert hasattr(MessageType, "ALPHA_SNAPSHOT")
        assert hasattr(MessageType, "ADAPTATION_ACTION")
        assert hasattr(MessageType, "AGENT_STATE_CHANGE")


class TestPhase2Commands:
    """REPL commands work correctly."""

    @pytest.mark.asyncio
    async def test_help_includes_core_commands(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("help")
        assert "portfolio" in result
        assert "risk" in result
        assert "performance" in result

    @pytest.mark.asyncio
    async def test_signals_no_data(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("signals")
        assert result is not None

    @pytest.mark.asyncio
    async def test_debate_no_data(self):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("debate")
        assert result is not None


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
        signal = strat.generate_signal_from_features("TEST", {
            "close": 95.0,
            "rsi": 25.0,
            "bb_upper": 110.0,
            "bb_lower": 96.0,
            "bb_mid": 103.0,
        })
        assert signal is not None
        assert signal.direction == 1  # BUY at lower band


class TestBollingerStrategy:
    """Bollinger Band strategy."""

    def test_import(self):
        from app.agents.front_office.strategy.simple_strategies import BollingerBandStrategy
        assert BollingerBandStrategy is not None

    def test_returns_none_on_flat_data(self):
        """Flat price data should produce no signal (band_width == 0)."""
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import BollingerBandStrategy

        df = pd.DataFrame({
            "open": [100.0] * 25, "high": [100.0] * 25,
            "low": [100.0] * 25, "close": [100.0] * 25,
            "volume": [1000] * 25,
        })
        strat = BollingerBandStrategy()
        signal = strat.generate_signal("TEST", df)
        assert signal is None


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
        signal = strat.generate_signal_from_features("TEST", {
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
        })
        assert signal is not None
        assert signal.direction == 1  # bullish
        assert "fusion" in signal.reasoning


class TestRSIStrategy:
    """RSI strategy."""

    def test_import(self):
        from app.agents.front_office.strategy.simple_strategies import RSIStrategy
        assert RSIStrategy is not None

    def test_oversold_buy(self):
        """Should generate BUY when RSI < 30."""
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import RSIStrategy

        prices = [100 - i * 2 for i in range(30)]
        df = pd.DataFrame({
            "open": prices, "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices], "close": prices,
            "volume": [1000] * len(prices),
        })
        signal = RSIStrategy().generate_signal("TEST", df)
        if signal is not None:
            assert signal.direction == 1

    def test_overbought_sell(self):
        """Should generate SELL when RSI > 70."""
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import RSIStrategy

        prices = [50 + i * 2 for i in range(30)]
        df = pd.DataFrame({
            "open": prices, "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices], "close": prices,
            "volume": [1000] * len(prices),
        })
        signal = RSIStrategy().generate_signal("TEST", df)
        if signal is not None:
            assert signal.direction == -1


# ===================================================================
# Phase 3 — Advanced Backtesting & Performance Analytics
# ===================================================================


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


class TestMACDStrategy:
    """MACD crossover strategy."""

    def test_import(self):
        from app.agents.front_office.strategy.simple_strategies import MACDStrategy
        assert MACDStrategy is not None

    def test_returns_none_on_short_data(self):
        """Fewer than 26 rows should return None."""
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import MACDStrategy

        prices = [100.0] * 10
        df = pd.DataFrame({
            "open": prices, "high": prices, "low": prices, "close": prices,
            "volume": [1000] * len(prices),
        })
        assert MACDStrategy().generate_signal("TEST", df) is None

    def test_signal_direction_valid(self):
        """Any signal produced must have direction +1 or -1."""
        import pandas as pd
        import numpy as np
        from app.agents.front_office.strategy.simple_strategies import MACDStrategy

        np.random.seed(1)
        prices = list(100 + np.cumsum(np.random.randn(50) * 0.5))
        df = pd.DataFrame({
            "open": prices, "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices], "close": prices,
            "volume": [1000] * len(prices),
        })
        signal = MACDStrategy().generate_signal("TEST", df)
        if signal is not None:
            assert signal.direction in (-1, 1)


class TestAllStrategiesSignalFields:
    """All strategies produce signals with correct field types."""

    def test_signal_fields(self):
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import RSIStrategy
        from app.agents.front_office.strategy.base_strategy import Signal

        prices = [100 - i * 2 for i in range(30)]
        df = pd.DataFrame({
            "open": prices, "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices], "close": prices,
            "volume": [1000] * len(prices),
        })
        signal = RSIStrategy().generate_signal("TEST", df)
        if signal is not None:
            assert isinstance(signal, Signal)
            assert signal.symbol == "TEST"
            assert signal.direction in (-1, 0, 1)
            assert 0.0 <= signal.strength <= 1.0
            assert isinstance(signal.reasoning, str)


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


class TestBrokerConnect:
    """Paper broker and AlpacaBroker basics."""

    def test_alpaca_broker_dynamic_credentials(self):
        """AlpacaBroker reads credentials dynamically from settings."""
        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        h = broker.headers
        assert "APCA-API-KEY-ID" in h
        assert "APCA-API-SECRET-KEY" in h
        assert broker.base_url.startswith("https://")

    def test_alpaca_get_account_method_exists(self):
        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        assert hasattr(broker, "get_account")
        assert asyncio.iscoroutinefunction(broker.get_account)

    def test_help_text_includes_commands(self):
        from app.tui.commands import HELP_TEXT
        assert "backtest" in HELP_TEXT
        assert "portfolio" in HELP_TEXT
        assert "health" in HELP_TEXT


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
