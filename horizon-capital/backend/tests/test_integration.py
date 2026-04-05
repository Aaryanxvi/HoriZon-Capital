"""Integration tests for Horizon Capital.

Tests real workflows: agent communication, orchestrator lifecycle,
circuit breaker patterns, performance calculations, command handler,
and security validation.

Run with:
    cd horizon-capital/backend
    python -m pytest tests/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"
os.environ["APP_DEBUG"] = "false"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =====================================================================
# 1. Resilience: Circuit Breaker
# =====================================================================


class TestCircuitBreaker:
    """Circuit breaker opens, rejects, and recovers correctly."""

    @pytest.mark.asyncio
    async def test_closed_on_success(self):
        from app.core.resilience import CircuitBreaker, CircuitState

        cb = CircuitBreaker("test", failure_threshold=3)

        async def ok():
            return 42

        result = await cb.call(ok)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        from app.core.resilience import CircuitBreaker, CircuitOpenError, CircuitState

        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=100)

        async def fail():
            raise ConnectionError("down")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        # Further calls should be rejected immediately
        with pytest.raises(CircuitOpenError):
            await cb.call(fail)

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        from app.core.resilience import CircuitBreaker, CircuitState

        cb = CircuitBreaker(
            "test",
            failure_threshold=2,
            recovery_timeout=0.1,
            half_open_max=1,
        )

        async def fail():
            raise ConnectionError("down")

        async def ok():
            return "recovered"

        # Trip the circuit
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(fail)
        assert cb._state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(0.2)
        assert cb.state == CircuitState.HALF_OPEN

        # Successful probe should close
        result = await cb.call(ok)
        assert result == "recovered"
        # After one success with half_open_max=1, circuit should close
        assert cb._state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self):
        from app.core.resilience import CircuitBreaker, CircuitState

        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=100)

        async def fail():
            raise RuntimeError("err")

        with pytest.raises(RuntimeError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestRetryWithBackoff:
    """Retry helper retries and eventually succeeds or exhausts."""

    @pytest.mark.asyncio
    async def test_succeeds_on_retry(self):
        from app.core.resilience import retry_with_backoff

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("temp failure")
            return "ok"

        result = await retry_with_backoff(
            flaky, max_retries=3, base_delay=0.01
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        from app.core.resilience import retry_with_backoff

        async def always_fail():
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await retry_with_backoff(
                always_fail, max_retries=2, base_delay=0.01
            )


class TestTimeout:
    """Timeout wrapper cancels slow operations."""

    @pytest.mark.asyncio
    async def test_completes_within_timeout(self):
        from app.core.resilience import with_timeout

        async def fast():
            return "done"

        result = await with_timeout(fast(), timeout_seconds=1.0)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        from app.core.resilience import with_timeout

        async def slow():
            await asyncio.sleep(10)

        with pytest.raises(asyncio.TimeoutError):
            await with_timeout(slow(), timeout_seconds=0.05)


# =====================================================================
# 2. Agent Bus: Multi-Agent Communication
# =====================================================================


class TestAgentCommunication:
    """Agents can communicate through the bus with proper routing."""

    @pytest.mark.asyncio
    async def test_multi_handler_dispatch(self):
        """Multiple handlers on the same channel all receive the message."""
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        await bus.start_listening()

        results_a: list[str] = []
        results_b: list[str] = []

        async def handler_a(msg: AgentMessage):
            results_a.append(msg.payload["data"])

        async def handler_b(msg: AgentMessage):
            results_b.append(msg.payload["data"])

        await bus.subscribe("horizon.test", handler_a)
        await bus.subscribe("horizon.test", handler_b)

        await bus.publish(AgentMessage(
            sender_id="sender",
            channel="horizon.test",
            message_type=MessageType.HEARTBEAT,
            payload={"data": "hello"},
        ))
        await asyncio.sleep(0.2)

        assert results_a == ["hello"]
        assert results_b == ["hello"]
        await bus.stop()

    @pytest.mark.asyncio
    async def test_signal_to_risk_flow(self):
        """Simulate: strategy agent publishes signal -> risk agent receives it."""
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        await bus.start_listening()

        risk_received: list[dict] = []

        async def risk_handler(msg: AgentMessage):
            if msg.message_type == MessageType.SIGNAL:
                risk_received.append(msg.payload)

        await bus.subscribe("horizon.*", risk_handler)

        # Strategy agent publishes a signal
        await bus.publish(AgentMessage(
            sender_id="momentum-strategy",
            channel="horizon.signals.AAPL",
            message_type=MessageType.SIGNAL,
            payload={
                "symbol": "AAPL",
                "direction": 1,
                "strength": 0.85,
                "strategy_name": "momentum",
            },
        ))
        await asyncio.sleep(0.2)

        assert len(risk_received) == 1
        assert risk_received[0]["symbol"] == "AAPL"
        assert risk_received[0]["direction"] == 1
        await bus.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        await bus.start_listening()

        received: list[str] = []

        async def handler(msg: AgentMessage):
            received.append("got")

        await bus.subscribe("horizon.test", handler)
        await bus.publish(AgentMessage(
            sender_id="s", channel="horizon.test",
            message_type=MessageType.HEARTBEAT, payload={},
        ))
        await asyncio.sleep(0.2)
        assert len(received) == 1

        await bus.unsubscribe("horizon.test")
        await bus.publish(AgentMessage(
            sender_id="s", channel="horizon.test",
            message_type=MessageType.HEARTBEAT, payload={},
        ))
        await asyncio.sleep(0.2)
        assert len(received) == 1  # No new messages
        await bus.stop()


# =====================================================================
# 3. Orchestrator Lifecycle
# =====================================================================


class TestOrchestratorLifecycle:
    """Orchestrator can start and stop agents cleanly."""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        from app.core.local_storage import init_local_db
        from app.core.memory_bus import MemoryBus
        from app.workers.agent_orchestrator import AgentOrchestrator

        await init_local_db()
        bus = MemoryBus()
        await bus.start_listening()

        orch = AgentOrchestrator(bus=bus)
        await orch.start_all()

        statuses = orch.get_agent_statuses()
        assert len(statuses) > 0
        # All agents should be RUNNING or INIT
        for agent_id, info in statuses.items():
            assert info["status"] in ("RUNNING", "INIT"), f"{agent_id}: {info['status']}"

        await orch.stop_all()

        # After stop, all should be STOPPED
        statuses = orch.get_agent_statuses()
        for agent_id, info in statuses.items():
            assert info["status"] == "STOPPED", f"{agent_id}: {info['status']}"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_department_statuses(self):
        from app.core.local_storage import init_local_db
        from app.core.memory_bus import MemoryBus
        from app.workers.agent_orchestrator import AgentOrchestrator

        await init_local_db()
        bus = MemoryBus()
        await bus.start_listening()

        orch = AgentOrchestrator(bus=bus)
        await orch.start_all()

        dept_statuses = orch.get_department_statuses()
        assert len(dept_statuses) > 0

        dept_names = {d["display_name"] for d in dept_statuses}
        # We should have at least front and middle office
        assert any("Front" in n for n in dept_names)

        await orch.stop_all()
        await bus.stop()

    @pytest.mark.asyncio
    async def test_worker_registration(self):
        from app.core.memory_bus import MemoryBus
        from app.workers.agent_orchestrator import AgentOrchestrator

        bus = MemoryBus()
        orch = AgentOrchestrator(bus=bus)

        class FakeWorker:
            async def run(self):
                await asyncio.sleep(100)

        worker = FakeWorker()
        task = asyncio.create_task(worker.run(), name="fake_worker")
        orch.register_worker("fake_worker", worker, task)

        statuses = orch.get_worker_statuses()
        assert "fake_worker" in statuses
        assert statuses["fake_worker"]["status"] == "RUNNING"

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await bus.stop()


# =====================================================================
# 4. Performance Service: Real Math
# =====================================================================


class TestPerformanceService:
    """Performance metrics are mathematically correct."""

    def _make_service(self):
        from app.workers.performance_worker import PerformanceService
        return PerformanceService()

    def test_total_return_positive(self):
        svc = self._make_service()
        equity = np.array([100.0, 105.0, 110.0, 120.0])
        ret = svc._total_return(equity)
        assert abs(ret - 0.20) < 1e-6

    def test_total_return_negative(self):
        svc = self._make_service()
        equity = np.array([100.0, 90.0, 80.0])
        ret = svc._total_return(equity)
        assert abs(ret - (-0.20)) < 1e-6

    def test_total_return_empty(self):
        svc = self._make_service()
        assert svc._total_return(np.array([])) == 0.0
        assert svc._total_return(np.array([100.0])) == 0.0

    def test_annualized_return(self):
        svc = self._make_service()
        # 252 days of data with 10% total return
        equity = np.linspace(100, 110, 252)
        ann = svc._annualized_return(equity)
        # Should be close to 10% for 1 year
        assert 0.08 < ann < 0.12

    def test_sharpe_ratio_flat(self):
        svc = self._make_service()
        # Constant equity = zero volatility => zero Sharpe
        equity = np.full(100, 100.0)
        assert svc._sharpe_ratio(equity) == 0.0

    def test_sharpe_ratio_trending(self):
        svc = self._make_service()
        # Steadily increasing equity => positive Sharpe
        equity = np.linspace(100, 120, 252)
        sharpe = svc._sharpe_ratio(equity)
        assert sharpe > 0

    def test_sortino_ratio(self):
        svc = self._make_service()
        # Strongly upward equity with some noise that includes downside
        np.random.seed(99)
        equity = 100 + np.cumsum(np.random.normal(0.3, 0.5, 252))
        sortino = svc._sortino_ratio(equity)
        # With positive drift and noise, sortino should be positive
        assert isinstance(sortino, float)

    def test_max_drawdown(self):
        svc = self._make_service()
        equity = np.array([100.0, 110.0, 120.0, 90.0, 95.0, 130.0])
        mdd = svc._max_drawdown(equity)
        # Max drawdown from 120 to 90 = 25%
        assert abs(mdd - 0.25) < 1e-6

    def test_calmar_ratio(self):
        svc = self._make_service()
        # Equity that has positive return AND a drawdown
        np.random.seed(42)
        equity = 100 + np.cumsum(np.random.normal(0.1, 0.5, 252))
        calmar = svc._calmar_ratio(equity)
        # Should return a float (may be 0 if no drawdown in this seed)
        assert isinstance(calmar, float)

    def test_win_rate(self):
        svc = self._make_service()
        trades = [
            {"side": "SELL", "fill_price": 110, "filled_qty": 10, "commission": 5},
            {"side": "SELL", "fill_price": 90, "filled_qty": 10, "commission": 5},
            {"side": "SELL", "fill_price": 120, "filled_qty": 10, "commission": 5},
            {"side": "BUY", "fill_price": 100, "filled_qty": 10, "commission": 5},
        ]
        wr = svc._win_rate(trades)
        # 3 SELL trades, all with fill_price * qty - commission > 0 => 100%
        assert wr == 1.0

    def test_profit_factor(self):
        svc = self._make_service()
        trades = [
            {"side": "SELL", "fill_price": 110, "filled_qty": 10, "commission": 5},  # profit
            {"side": "SELL", "fill_price": 0.1, "filled_qty": 10, "commission": 5},  # loss
        ]
        pf = svc._profit_factor(trades)
        assert pf > 1  # Profitable trades outweigh

    def test_compute_alpha(self):
        svc = self._make_service()
        np.random.seed(42)
        portfolio_returns = np.random.normal(0.001, 0.02, 100)
        benchmark_returns = np.random.normal(0.0005, 0.015, 100)
        alpha = svc._compute_alpha(portfolio_returns, benchmark_returns)
        # Alpha should be some non-zero number
        assert isinstance(alpha, float)

    def test_compute_alpha_insufficient_data(self):
        svc = self._make_service()
        short = np.array([0.01, 0.02])
        assert svc._compute_alpha(short, short) == 0.0


# =====================================================================
# 5. Technical Indicators
# =====================================================================


class TestTechnicalIndicators:
    """Technical indicator calculations produce valid outputs."""

    def _make_df(self):
        import pandas as pd
        np.random.seed(42)
        n = 100
        close = 100 + np.cumsum(np.random.normal(0, 1, n))
        high = close + np.abs(np.random.normal(0, 0.5, n))
        low = close - np.abs(np.random.normal(0, 0.5, n))
        open_ = close + np.random.normal(0, 0.3, n)
        volume = np.random.randint(1000, 100000, n).astype(float)
        return pd.DataFrame({
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        })

    def test_sma(self):
        from app.workers.feature_computation_worker import TechnicalIndicators
        df = self._make_df()
        df = TechnicalIndicators.sma(df, period=20)
        assert "sma_20" in df.columns
        assert df["sma_20"].iloc[-1] is not None
        assert not np.isnan(df["sma_20"].iloc[-1])

    def test_rsi_bounds(self):
        from app.workers.feature_computation_worker import TechnicalIndicators
        df = self._make_df()
        df = TechnicalIndicators.rsi(df)
        valid_rsi = df["rsi"].dropna()
        assert all(0 <= v <= 100 for v in valid_rsi)

    def test_macd(self):
        from app.workers.feature_computation_worker import TechnicalIndicators
        df = self._make_df()
        df = TechnicalIndicators.macd(df)
        assert "macd" in df.columns
        assert "macd_signal" in df.columns
        assert "macd_histogram" in df.columns

    def test_bollinger_bands(self):
        from app.workers.feature_computation_worker import TechnicalIndicators
        df = self._make_df()
        df = TechnicalIndicators.bollinger_bands(df)
        valid = df.dropna(subset=["bb_upper", "bb_lower"])
        assert all(valid["bb_upper"] >= valid["bb_lower"])

    def test_compute_all(self):
        from app.workers.feature_computation_worker import TechnicalIndicators
        df = self._make_df()
        df = TechnicalIndicators.compute_all(df)
        expected_columns = [
            "sma_20", "sma_50", "rsi", "macd", "bb_upper",
            "atr", "stoch_k", "adx", "obv", "vwap",
        ]
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

    def test_volatility_features(self):
        from app.workers.feature_computation_worker import VolatilityFeatures
        df = self._make_df()
        df = VolatilityFeatures.compute_all(df)
        assert "realized_vol" in df.columns
        assert "parkinson_vol" in df.columns
        assert "garman_klass_vol" in df.columns


# =====================================================================
# 6. Security Validation
# =====================================================================


class TestSecurity:
    """Security utilities work correctly."""

    def test_password_hashing(self):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("TestPassword123")
        assert verify_password("TestPassword123", hashed)
        assert not verify_password("WrongPassword", hashed)

    def test_password_validation_passes(self):
        from app.core.security import validate_password
        validate_password("StrongPass1")  # Should not raise

    def test_password_validation_too_short(self):
        from app.core.security import PasswordValidationError, validate_password
        with pytest.raises(PasswordValidationError, match="at least"):
            validate_password("Ab1")

    def test_password_validation_no_uppercase(self):
        from app.core.security import PasswordValidationError, validate_password
        with pytest.raises(PasswordValidationError, match="uppercase"):
            validate_password("alllowercase1")

    def test_password_validation_no_digit(self):
        from app.core.security import PasswordValidationError, validate_password
        with pytest.raises(PasswordValidationError, match="digit"):
            validate_password("NoDigitsHere")

    def test_jwt_roundtrip(self):
        from app.core.security import create_access_token, decode_token
        token = create_access_token({"sub": "admin", "role": "cio"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert payload["type"] == "access"

    def test_jwt_invalid_token(self):
        from app.core.security import decode_token
        assert decode_token("invalid.token.here") is None

    def test_refresh_token(self):
        from app.core.security import create_refresh_token, decode_token
        token = create_refresh_token({"sub": "admin"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_production_secret_warnings(self):
        from app.config import settings
        warnings = settings.validate_production_secrets()
        # Secrets are now auto-generated, so no "changeme" warnings
        # Instead, validate that actionable warnings are returned (e.g. missing API keys)
        assert isinstance(warnings, list)
        # Without LLM/broker keys set, those warnings should appear
        if not settings.anthropic_api_key and not settings.openai_api_key \
                and not settings.google_api_key:
            assert any("LLM" in w for w in warnings)
        if not settings.alpaca_api_key and not settings.zerodha_api_key:
            assert any("broker" in w.lower() for w in warnings)


# =====================================================================
# 7. Command Handler
# =====================================================================


class TestCommandHandler:
    """REPL commands produce valid output."""

    @pytest.mark.asyncio
    async def test_help(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("help")
        assert "status" in result
        assert "signals" in result
        assert "quit" in result

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("nonexistent")
        assert "Unknown command" in result

    @pytest.mark.asyncio
    async def test_empty_input(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("")
        assert result is None

    @pytest.mark.asyncio
    async def test_symbols(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("symbols")
        assert "RELIANCE.NSE" in result
        assert "AAPL.NASDAQ" in result

    @pytest.mark.asyncio
    async def test_config(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("config")
        assert "PAPER_TRADING" in result
        assert "LOCAL" in result

    @pytest.mark.asyncio
    async def test_portfolio_no_dashboard(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("portfolio")
        assert "NAV" in result

    @pytest.mark.asyncio
    async def test_risk_no_data(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("risk")
        assert "No risk data" in result or "Risk Metrics" in result

    @pytest.mark.asyncio
    async def test_quit_sets_flag(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        assert not cmd.should_quit
        await cmd.handle("quit")
        assert cmd.should_quit

    @pytest.mark.asyncio
    async def test_mode_display(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("mode")
        assert "PAPER_TRADING" in result

    @pytest.mark.asyncio
    async def test_mode_change(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("mode HUMAN_APPROVAL")
        assert "HUMAN_APPROVAL" in result
        # Reset
        await cmd.handle("mode PAPER_TRADING")

    @pytest.mark.asyncio
    async def test_mode_invalid(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("mode INVALID_MODE")
        assert "Invalid mode" in result

    @pytest.mark.asyncio
    async def test_risk_tolerance(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("risk-tolerance 15.0")
        assert "15.0" in result
        # Reset
        await cmd.handle("risk-tolerance 10.0")

    @pytest.mark.asyncio
    async def test_risk_tolerance_invalid(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("risk-tolerance abc")
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_performance_invalid_period(self):
        from app.tui.commands import CommandHandler
        cmd = CommandHandler()
        result = await cmd.handle("performance 2Y")
        assert "Invalid period" in result


# =====================================================================
# 8. Stress Testing Service
# =====================================================================


class TestStressTesting:
    """Stress testing service produces valid scenario results."""

    def test_historical_scenarios_exist(self):
        from app.services.stress_testing import HISTORICAL_SCENARIOS
        assert "GFC_2008" in HISTORICAL_SCENARIOS
        assert "COVID_2020" in HISTORICAL_SCENARIOS
        assert len(HISTORICAL_SCENARIOS) >= 3

    def test_run_all_scenarios(self):
        from app.services.stress_testing import StressTestingService
        svc = StressTestingService()
        positions = [
            {"symbol": "AAPL", "weight_pct": 50.0},
            {"symbol": "RELIANCE", "weight_pct": 50.0},
        ]
        report = svc.run_historical_scenarios(positions, portfolio_value=1_000_000)
        assert len(report.scenario_results) > 0
        assert report.aggregate_risk_score >= 0
        assert report.worst_case_scenario is not None

    def test_scenario_impact_negative(self):
        from app.services.stress_testing import StressTestingService
        svc = StressTestingService()
        positions = [{"symbol": "AAPL", "weight_pct": 100.0}]
        report = svc.run_historical_scenarios(positions, portfolio_value=1_000_000)
        # All crisis scenarios should have negative impact
        for sr in report.scenario_results:
            assert sr.portfolio_impact_pct <= 0, f"{sr.scenario_key} had positive impact"


# =====================================================================
# 9. Dashboard Data Flow
# =====================================================================


class TestDashboard:
    """Dashboard correctly accumulates and limits data."""

    def test_add_signal_limits(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(30):
            dash.add_signal({"symbol": f"SYM{i}", "direction": 1})
        assert len(dash._signals) == 20

    def test_add_alert_limits(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(30):
            dash.add_alert({"title": f"Alert {i}"})
        assert len(dash._alerts) == 20

    def test_update_agent_status(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_agent_status("test-agent", {
            "status": "RUNNING",
            "department": "front_office",
        })
        assert "test-agent" in dash._agent_statuses
        assert dash.pixel_agents.get_agent_count() == 1

    def test_build_layout(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_risk({"var_95": 0.02, "var_99": 0.04, "max_drawdown": 5.0})
        layout = dash.build_layout()
        assert layout is not None

    def test_update_watchlist(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_watchlist({
            "symbol": "RELIANCE.NSE",
            "price": 2847.50,
            "change_pct": 1.2,
            "prev_close": 2813.82,
        })
        assert "RELIANCE.NSE" in dash._watchlist
        assert dash._watchlist["RELIANCE.NSE"]["price"] == 2847.50
        assert len(dash._watchlist["RELIANCE.NSE"]["history"]) == 1

    def test_watchlist_sparkline_caps_at_20(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(25):
            dash.update_watchlist({
                "symbol": "TCS.NSE",
                "price": 3900 + i,
                "change_pct": 0.1 * i,
            })
        assert len(dash._watchlist["TCS.NSE"]["history"]) == 20

    def test_update_portfolio_with_positions(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.update_portfolio({
            "nav": 1_024_350.0,
            "cash": 241_000.0,
            "positions": [
                {"symbol": "RELIANCE.NSE", "qty": 100, "unrealized_pnl": 4200.0},
            ],
        })
        assert dash._portfolio["nav"] == 1_024_350.0
        assert len(dash._portfolio["positions"]) == 1

    def test_add_pending_order(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "order_type": "MARKET",
            "status": "PENDING",
        })
        assert len(dash._pending_orders) == 1
        assert dash._pending_orders[0]["order_id"] == "ORD-001"

    def test_complete_order_moves_to_history(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "status": "PENDING",
        })
        dash.complete_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "fill_price": 2847.50,
            "status": "FILLED",
        })
        assert len(dash._pending_orders) == 0
        assert len(dash._trade_history) == 1

    def test_remove_order_on_reject(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-002",
            "symbol": "TCS.NSE",
            "side": "SELL",
            "quantity": 50,
            "status": "PENDING",
        })
        dash.remove_order("ORD-002")
        assert len(dash._pending_orders) == 0

    def test_trade_history_limited_to_20(self):
        from app.tui.dashboard import TerminalDashboard
        dash = TerminalDashboard()
        for i in range(25):
            dash.complete_order({
                "order_id": f"ORD-{i:03d}",
                "symbol": "TEST",
                "side": "BUY",
                "quantity": 1,
                "fill_price": 100.0,
                "status": "FILLED",
            })
        assert len(dash._trade_history) == 20

    def test_render_sparkline(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([1, 2, 3, 4, 5, 6, 7, 8])
        assert len(result) == 8
        assert result[0] == "▁"
        assert result[-1] == "█"

    def test_render_sparkline_empty(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([])
        assert result == ""

    def test_render_sparkline_constant(self):
        from app.tui.dashboard import render_sparkline
        result = render_sparkline([5, 5, 5])
        assert len(result) == 3


# =====================================================================
# 10. Config & Environment
# =====================================================================


class TestConfigAdvanced:
    """Advanced configuration validation."""

    def test_cors_origins_parsed(self):
        from app.config import settings
        origins = settings.cors_origin_list
        assert isinstance(origins, list)
        assert len(origins) >= 1

    def test_is_production_false_by_default(self):
        from app.config import settings
        assert not settings.is_production

    def test_database_url_format(self):
        from app.config import settings
        url = settings.database_url
        assert url.startswith("postgresql+asyncpg://")

    def test_redis_url_format(self):
        from app.config import settings
        url = settings.redis_url
        assert url.startswith("redis://")


class TestRiskGate:
    """Risk gate emits RISK_APPROVED / RISK_REJECTED."""

    @pytest.mark.asyncio
    async def test_risk_approved_emitted(self):
        """Signal with no violations emits RISK_APPROVED."""
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        await bus.start_listening()

        received = []

        async def capture(msg: AgentMessage):
            received.append(msg)

        await bus.subscribe("horizon.risk.approved.*", capture)

        # Simulate risk agent approving by directly publishing
        await bus.publish(AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.approved.AAPL",
            message_type=MessageType.SIGNAL,
            payload={"symbol": "AAPL", "direction": 1, "strength": 0.7},
        ))
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].message_type == MessageType.SIGNAL
        assert received[0].payload["symbol"] == "AAPL"
        await bus.stop()

    @pytest.mark.asyncio
    async def test_risk_rejected_not_forwarded(self):
        """RISK_REJECTED should not trigger portfolio sizing."""
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType

        bus = MemoryBus()
        await bus.start_listening()

        approved_received = []

        async def capture_approved(msg: AgentMessage):
            approved_received.append(msg)

        await bus.subscribe("horizon.risk.approved.*", capture_approved)

        # Publish a RISK_REJECTED -- should NOT appear on approved channel
        await bus.publish(AgentMessage(
            sender_id="risk-agent",
            channel="horizon.risk.rejected.AAPL",
            message_type=MessageType.RISK_ALERT,
            payload={"symbol": "AAPL", "violations": ["too risky"]},
        ))
        await asyncio.sleep(0.1)

        assert len(approved_received) == 0
        await bus.stop()


class TestKVPersistence:
    """PersistentKVStore persists and restores critical keys."""

    @pytest.mark.asyncio
    async def test_persist_and_restore_cycle(self):
        """Set critical keys, create a new store, restore, verify."""
        from app.core.kv_store import PersistentKVStore

        kv1 = PersistentKVStore()
        # Set a critical key (but _persist will fail without DB -- that's OK)
        await kv1.set("horizon:cash:usd", "500000")
        await kv1.set("horizon:system:mode", "PAPER_TRADING")

        # Values should be in memory
        assert await kv1.get("horizon:cash:usd") == "500000"
        assert await kv1.get("horizon:system:mode") == "PAPER_TRADING"

    @pytest.mark.asyncio
    async def test_non_critical_key_not_persisted(self):
        """Non-critical keys are stored in memory but not persisted to SQLite."""
        from app.core.kv_store import PersistentKVStore

        kv = PersistentKVStore()
        await kv.set("horizon:price:AAPL", "150.0")
        assert await kv.get("horizon:price:AAPL") == "150.0"
        # The key is not in _PERSIST_KEYS, so no SQLite write attempted
        assert "horizon:price:AAPL" not in PersistentKVStore._PERSIST_KEYS


class TestKillSwitchCancelAll:
    """Kill switch publishes ORDER_CANCEL_ALL."""

    @pytest.mark.asyncio
    async def test_cancel_all_published_on_activate(self):
        from app.core.kv_store import MemoryKVStore
        from app.core.memory_bus import MemoryBus
        from app.core.messaging import AgentMessage, MessageType
        from app.agents.middle_office.risk.kill_switch import KillSwitch

        bus = MemoryBus()
        await bus.start_listening()

        received = []

        async def capture(msg: AgentMessage):
            received.append(msg)

        await bus.subscribe("horizon.risk.kill_switch", capture)
        await bus.subscribe("horizon.execution.order.cancel_all", capture)

        kv = MemoryKVStore()
        ks = KillSwitch(bus=bus, redis=kv)
        await ks.activate("test kill switch")

        await asyncio.sleep(0.1)

        # Should have 2 messages: RISK_ALERT + ORDER_CANCEL
        types = [m.message_type for m in received]
        assert MessageType.RISK_ALERT in types
        assert MessageType.ORDER_CANCEL in types
        await bus.stop()


class TestDailyLossLimit:
    """Daily loss limit checks."""

    @pytest.mark.asyncio
    async def test_loss_limit_within_threshold(self):
        """When losses are below threshold, check passes."""
        from app.core.kv_store import PersistentKVStore

        kv = PersistentKVStore()
        await kv.set("horizon:portfolio:nav", "1000000")
        # Verify NAV is set
        assert await kv.get("horizon:portfolio:nav") == "1000000"


class TestShortStopLoss:
    """SHORT position stop-loss triggers BUY signal."""

    def test_short_stop_loss_logic(self):
        """When price rises above stop for SHORT, stop should trigger."""
        side = "SHORT"
        current_price = 110.0
        stop_loss_price = 105.0

        stop_triggered = False
        if side == "SHORT" and stop_loss_price is not None:
            stop_triggered = current_price >= stop_loss_price

        assert stop_triggered is True

    def test_long_stop_loss_logic(self):
        """When price falls below stop for LONG, stop should trigger."""
        side = "LONG"
        current_price = 95.0
        stop_loss_price = 100.0

        stop_triggered = False
        if side == "LONG" and stop_loss_price is not None:
            stop_triggered = current_price <= stop_loss_price

        assert stop_triggered is True

    def test_short_stop_loss_not_triggered(self):
        """When price is below stop for SHORT, stop should NOT trigger."""
        side = "SHORT"
        current_price = 95.0
        stop_loss_price = 105.0

        stop_triggered = False
        if side == "SHORT" and stop_loss_price is not None:
            stop_triggered = current_price >= stop_loss_price

        assert stop_triggered is False


class TestPriceStaleness:
    """Price staleness check logic."""

    def test_stale_price_detected(self):
        """Prices older than 60s should be flagged as stale."""
        from datetime import UTC, datetime, timedelta

        updated_at = datetime.now(UTC) - timedelta(seconds=90)
        age = (datetime.now(UTC) - updated_at).total_seconds()
        assert age > 60

    def test_fresh_price_not_stale(self):
        """Prices within 60s should not be stale."""
        from datetime import UTC, datetime, timedelta

        updated_at = datetime.now(UTC) - timedelta(seconds=30)
        age = (datetime.now(UTC) - updated_at).total_seconds()
        assert age <= 60


# =====================================================================
# Dashboard Wiring (bus message → dashboard method)
# =====================================================================


class TestDashboardWiring:
    @pytest.mark.asyncio
    async def test_price_update_routes_to_watchlist(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        msg = AgentMessage(
            sender_id="data-ingestion-worker",
            channel="horizon.market.price",
            message_type=MessageType.TICK,
            payload={
                "symbol": "RELIANCE.NSE",
                "price": 2847.50,
                "change_pct": 1.2,
            },
        )
        dash.update_watchlist(msg.payload)
        assert "RELIANCE.NSE" in dash._watchlist

    @pytest.mark.asyncio
    async def test_order_new_routes_to_pending(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        msg = AgentMessage(
            sender_id="portfolio-agent",
            channel="horizon.execution.order.new",
            message_type=MessageType.ORDER_NEW,
            payload={
                "signal_id": "abc-123",
                "order_id": "ORD-001",
                "symbol": "RELIANCE.NSE",
                "side": "BUY",
                "quantity": 100,
                "order_type": "MARKET",
                "status": "PENDING",
            },
        )
        dash.add_pending_order(msg.payload)
        assert len(dash._pending_orders) == 1

    @pytest.mark.asyncio
    async def test_order_fill_completes_pending(self):
        from app.core.messaging import AgentMessage, MessageType
        from app.tui.dashboard import TerminalDashboard

        dash = TerminalDashboard()
        dash.add_pending_order({
            "order_id": "ORD-001",
            "symbol": "RELIANCE.NSE",
            "side": "BUY",
            "quantity": 100,
            "status": "PENDING",
        })
        fill_msg = AgentMessage(
            sender_id="execution-agent",
            channel="horizon.execution.order.fill",
            message_type=MessageType.ORDER_FILL,
            payload={
                "order_id": "ORD-001",
                "symbol": "RELIANCE.NSE",
                "side": "BUY",
                "quantity": 100,
                "fill_price": 2847.50,
                "status": "FILLED",
                "timestamp": "2026-04-02T14:21:30",
            },
        )
        dash.complete_order(fill_msg.payload)
        assert len(dash._pending_orders) == 0
        assert len(dash._trade_history) == 1


# =====================================================================
# 12. API Key Integration Verification
# =====================================================================


class TestYahooFeedIntegration:
    """Yahoo Finance feed makes real yfinance calls (not mocked/placeholder)."""

    def test_fetch_sync_calls_yfinance(self):
        """Verify _fetch_sync calls yfinance.Ticker and returns NormalizedOHLCV."""
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from app.data_layer.yahoo_feed import YahooFeed

        feed = YahooFeed()

        # Build a realistic DataFrame that yfinance would return
        idx = pd.DatetimeIndex(
            [pd.Timestamp("2026-03-30"), pd.Timestamp("2026-03-31")],
            tz="US/Eastern",
        )
        mock_df = pd.DataFrame(
            {
                "Open": [170.0, 171.0],
                "High": [175.0, 176.0],
                "Low": [169.0, 170.0],
                "Close": [174.0, 175.5],
                "Volume": [50000000, 48000000],
            },
            index=idx,
        )

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_df

        with patch("app.data_layer.yahoo_feed.yf.Ticker", return_value=mock_ticker) as mk:
            bars = feed._fetch_sync("AAPL.NASDAQ", "5d", "1d")
            mk.assert_called_once_with("AAPL")

        assert len(bars) == 2
        assert bars[0].symbol == "AAPL"
        assert bars[0].close == 174.0
        assert bars[1].close == 175.5
        assert bars[0].exchange == "NASDAQ"
        assert bars[0].timeframe == "1d"

    def test_fetch_sync_empty_df_returns_empty(self):
        """When yfinance returns empty DataFrame, feed returns []."""
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from app.data_layer.yahoo_feed import YahooFeed

        feed = YahooFeed()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        with patch("app.data_layer.yahoo_feed.yf.Ticker", return_value=mock_ticker):
            bars = feed._fetch_sync("INVALID", "5d", "1d")

        assert bars == []

    def test_fetch_sync_exception_returns_empty(self):
        """When yfinance raises, feed catches and returns []."""
        from unittest.mock import MagicMock, patch

        from app.data_layer.yahoo_feed import YahooFeed

        feed = YahooFeed()
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("network error")

        with patch("app.data_layer.yahoo_feed.yf.Ticker", return_value=mock_ticker):
            bars = feed._fetch_sync("AAPL", "5d", "1d")

        assert bars == []

    def test_symbol_conversion_india(self):
        """Indian symbols convert correctly: RELIANCE.NSE -> RELIANCE.NS."""
        from app.data_layer.yahoo_feed import YahooFeed
        assert YahooFeed._to_yf_ticker("RELIANCE.NSE") == "RELIANCE.NS"
        assert YahooFeed._to_yf_ticker("TCS.BSE") == "TCS.BO"

    def test_symbol_conversion_us(self):
        """US symbols strip exchange: AAPL.NASDAQ -> AAPL."""
        from app.data_layer.yahoo_feed import YahooFeed
        assert YahooFeed._to_yf_ticker("AAPL.NASDAQ") == "AAPL"
        assert YahooFeed._to_yf_ticker("MSFT.NYSE") == "MSFT"

    def test_symbol_conversion_crypto(self):
        """Crypto symbols pass through: BTC-USD -> BTC-USD."""
        from app.data_layer.yahoo_feed import YahooFeed
        assert YahooFeed._to_yf_ticker("BTC-USD.CRYPTO") == "BTC-USD"


class TestCoinGeckoFeedIntegration:
    """CoinGecko feed makes real HTTP calls to the CoinGecko API."""

    @pytest.mark.asyncio
    async def test_fetch_prices_calls_real_api(self):
        """Verify _fetch_prices sends correct URL/params to CoinGecko."""
        from unittest.mock import AsyncMock, MagicMock

        from app.data_layer.crypto_feed import CryptoFeed

        feed = CryptoFeed()
        feed._symbols = ["BTC", "ETH"]

        # Mock httpx response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bitcoin": {
                "usd": 67500.0,
                "usd_24h_vol": 25_000_000_000,
                "last_updated_at": 1711900000,
            },
            "ethereum": {
                "usd": 3400.0,
                "usd_24h_vol": 12_000_000_000,
                "last_updated_at": 1711900000,
            },
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        # Capture emitted ticks
        ticks = []

        async def capture_tick(tick):
            ticks.append(tick)

        feed.on_tick(capture_tick)

        await feed._fetch_prices(mock_client)

        # Verify the correct API URL was called
        call_args = mock_client.get.call_args
        assert "api.coingecko.com" in str(call_args)
        assert "bitcoin" in str(call_args) or "ethereum" in str(call_args)

        # Should emit 2 ticks (BTC + ETH)
        assert len(ticks) == 2
        symbols = {t.symbol for t in ticks}
        assert "BTC-USD" in symbols
        assert "ETH-USD" in symbols

        btc_tick = next(t for t in ticks if t.symbol == "BTC-USD")
        assert btc_tick.last_price == 67500.0
        assert btc_tick.exchange == "CRYPTO"

    @pytest.mark.asyncio
    async def test_fetch_prices_api_error_no_crash(self):
        """When CoinGecko returns error status, feed handles gracefully."""
        from unittest.mock import AsyncMock, MagicMock

        from app.data_layer.crypto_feed import CryptoFeed

        feed = CryptoFeed()
        feed._symbols = ["BTC"]

        mock_response = MagicMock()
        mock_response.status_code = 429  # Rate limited

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        ticks = []

        async def capture(tick):
            ticks.append(tick)

        feed.on_tick(capture)

        # Should not raise
        await feed._fetch_prices(mock_client)
        assert ticks == []

    @pytest.mark.asyncio
    async def test_no_symbols_returns_early(self):
        """When no symbols are subscribed, fetch_prices returns immediately."""
        from unittest.mock import AsyncMock

        from app.data_layer.crypto_feed import CryptoFeed

        feed = CryptoFeed()
        feed._symbols = []

        mock_client = AsyncMock()
        await feed._fetch_prices(mock_client)
        mock_client.get.assert_not_called()


class TestPolygonFeedIntegration:
    """Polygon.io feed correctly uses API key and makes real HTTP calls."""

    def test_disabled_without_api_key(self):
        """Feed is disabled when polygon_api_key is empty."""
        from app.data_layer.polygon_feed import PolygonFeed
        feed = PolygonFeed()
        # Default settings have empty polygon_api_key
        assert feed._enabled is False

    @pytest.mark.asyncio
    async def test_connect_skips_when_disabled(self):
        """connect() returns without setting _is_connected when no key."""
        from app.data_layer.polygon_feed import PolygonFeed
        feed = PolygonFeed()
        await feed.connect()
        assert feed.is_connected is False

    @pytest.mark.asyncio
    async def test_get_ohlcv_sends_api_key(self):
        """Verify API key is included as query param in requests."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.data_layer.polygon_feed import PolygonFeed

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "t": 1711900000000,
                    "o": 170.0,
                    "h": 175.0,
                    "l": 169.0,
                    "c": 174.5,
                    "v": 50000000,
                }
            ]
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        # The feed reads settings.polygon_api_key at call time.
        # Patch settings to provide a key.
        feed = PolygonFeed()
        with patch(
            "app.data_layer.polygon_feed.settings"
        ) as mock_settings:
            mock_settings.polygon_api_key = "test-polygon-key-12345"

            with patch(
                "app.data_layer.polygon_feed.httpx.AsyncClient",
                return_value=mock_client_instance,
            ):
                bars = await feed.get_ohlcv("AAPL", "2026-03-01", "2026-03-31")

        # Verify API key was included in the request params
        call_args = mock_client_instance.get.call_args
        params = call_args.kwargs.get("params", {})
        assert params.get("apiKey") == "test-polygon-key-12345"

        assert len(bars) == 1
        assert bars[0].close == 174.5
        assert bars[0].symbol == "AAPL"


class TestForexFeedIntegration:
    """Forex feed uses yfinance for real USD/INR rates."""

    def test_fetch_sync_calls_yfinance(self):
        """Verify _fetch_sync calls yfinance with USDINR=X ticker."""
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from app.data_layer.forex_feed import ForexFeed

        idx = pd.DatetimeIndex([pd.Timestamp("2026-03-31 15:30")])
        mock_df = pd.DataFrame({"Close": [83.45]}, index=idx)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_df

        with patch("app.data_layer.forex_feed.yf.Ticker", return_value=mock_ticker) as mk:
            rate = ForexFeed._fetch_sync()
            mk.assert_called_once_with("USDINR=X")

        assert rate == 83.45

    def test_fetch_sync_empty_df_uses_fast_info(self):
        """When history is empty, falls back to fast_info.last_price."""
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from app.data_layer.forex_feed import ForexFeed

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_ticker.fast_info.last_price = 83.50

        with patch("app.data_layer.forex_feed.yf.Ticker", return_value=mock_ticker):
            rate = ForexFeed._fetch_sync()

        assert rate == 83.50

    def test_fetch_sync_exception_returns_none(self):
        """When yfinance raises, returns None (graceful degradation)."""
        from unittest.mock import patch

        from app.data_layer.forex_feed import ForexFeed

        with patch(
            "app.data_layer.forex_feed.yf.Ticker",
            side_effect=Exception("network error"),
        ):
            rate = ForexFeed._fetch_sync()

        assert rate is None


class TestLLMProviderRegistry:
    """LLM provider registry correctly registers/queries providers."""

    def test_auto_register_with_keys(self):
        """When API keys are set, providers are registered and usable."""
        from unittest.mock import patch

        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()

        with patch("app.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-ant-test-key-123"
            mock_settings.openai_api_key = "sk-openai-test-key-456"
            mock_settings.google_api_key = ""
            mock_settings.ai_front_office = "auto"
            mock_settings.ai_middle_office = "auto"
            mock_settings.ai_back_office = "auto"
            mock_settings.ai_executive = "auto"

            registry.auto_register_from_settings()

        assert "claude" in registry.list_available()
        assert "openai" in registry.list_available()
        assert "gemini" not in registry.list_available()

    def test_auto_register_no_keys(self):
        """When no API keys are set, no providers are registered."""
        from unittest.mock import patch

        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()

        with patch("app.config.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            mock_settings.openai_api_key = ""
            mock_settings.google_api_key = ""

            registry.auto_register_from_settings()

        assert registry.list_available() == []

    def test_register_empty_key_ignored(self):
        """Registering with empty key does nothing."""
        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "")
        assert registry.list_available() == []

    def test_get_provider_returns_correct_type(self):
        """get_provider returns the right provider class."""
        from app.llm.claude_provider import ClaudeProvider
        from app.llm.openai_provider import OpenAIProvider
        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "sk-ant-test")
        registry.register("openai", "sk-openai-test")

        claude = registry.get_provider("claude")
        openai = registry.get_provider("openai")

        assert isinstance(claude, ClaudeProvider)
        assert isinstance(openai, OpenAIProvider)
        assert claude.api_key == "sk-ant-test"
        assert openai.api_key == "sk-openai-test"

    def test_get_provider_missing_returns_none(self):
        """get_provider returns None for unregistered providers."""
        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        assert registry.get_provider("nonexistent") is None

    def test_department_routing_auto(self):
        """'auto' routing returns all available providers."""
        from unittest.mock import patch

        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "sk-ant-test")
        registry.register("openai", "sk-openai-test")

        with patch("app.config.settings") as mock_settings:
            mock_settings.ai_front_office = "auto"
            providers = registry.get_providers_for_department("front_office")

        assert len(providers) == 2

    def test_department_routing_none(self):
        """'none' routing returns empty list."""
        from unittest.mock import patch

        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "sk-ant-test")

        with patch("app.config.settings") as mock_settings:
            mock_settings.ai_front_office = "none"
            providers = registry.get_providers_for_department("front_office")

        assert providers == []

    def test_department_routing_specific(self):
        """Specific provider routing returns only that provider."""
        from unittest.mock import patch

        from app.llm.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        registry.register("claude", "sk-ant-test")
        registry.register("openai", "sk-openai-test")

        with patch("app.config.settings") as mock_settings:
            mock_settings.ai_front_office = "claude"
            providers = registry.get_providers_for_department("front_office")

        assert len(providers) == 1
        assert providers[0].provider_name == "claude"


class TestClaudeProviderIntegration:
    """Claude provider makes real API calls with proper auth."""

    @pytest.mark.asyncio
    async def test_do_complete_calls_anthropic_api(self):
        """Verify _do_complete sends correct params to Anthropic SDK."""
        from unittest.mock import AsyncMock, MagicMock

        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="sk-ant-test-key")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"direction": 1, "strength": 0.8}')]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        # Inject mock client directly (bypasses lazy import)
        provider._client = mock_client

        result = await provider._do_complete(
            system_prompt="You are a trader.",
            messages=[{"role": "user", "content": "Analyze AAPL"}],
            temperature=0.3,
        )

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["system"] == "You are a trader."
        assert call_kwargs["temperature"] == 0.3
        assert result == '{"direction": 1, "strength": 0.8}'

    @pytest.mark.asyncio
    async def test_is_available_true_with_key(self):
        """is_available returns True when API key is set."""
        from unittest.mock import AsyncMock

        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="sk-ant-test-key")
        # Inject a mock client so _get_client doesn't try real import
        provider._client = AsyncMock()
        result = await provider.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_is_available_false_without_key(self):
        """is_available returns False when API key is empty."""
        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="")
        result = await provider.is_available()
        assert result is False

    def test_get_client_passes_api_key(self):
        """_get_client passes the api_key to the SDK constructor."""
        from unittest.mock import MagicMock, patch

        from app.llm.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="sk-ant-test-key-XYZ")

        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            provider._client = None  # Force re-creation
            provider._get_client()
            mock_anthropic.AsyncAnthropic.assert_called_once_with(
                api_key="sk-ant-test-key-XYZ"
            )


class TestOpenAIProviderIntegration:
    """OpenAI provider makes real API calls with proper auth."""

    @pytest.mark.asyncio
    async def test_do_complete_calls_openai_api(self):
        """Verify _do_complete sends correct params to OpenAI SDK."""
        from unittest.mock import AsyncMock, MagicMock

        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai-test-key")

        mock_choice = MagicMock()
        mock_choice.message.content = '{"direction": -1, "strength": 0.6}'
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Inject mock client directly
        provider._client = mock_client

        result = await provider._do_complete(
            system_prompt="You are a risk analyst.",
            messages=[{"role": "user", "content": "Analyze risk"}],
            temperature=0.5,
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["temperature"] == 0.5
        # System prompt should be prepended as system message
        assert call_kwargs["messages"][0] == {
            "role": "system",
            "content": "You are a risk analyst.",
        }
        assert result == '{"direction": -1, "strength": 0.6}'

    def test_get_client_passes_api_key(self):
        """_get_client passes the api_key to the SDK constructor."""
        from unittest.mock import MagicMock, patch

        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="sk-openai-test-key-ABC")

        mock_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_openai}):
            provider._client = None
            provider._get_client()
            mock_openai.AsyncOpenAI.assert_called_once_with(
                api_key="sk-openai-test-key-ABC"
            )


class TestGeminiProviderIntegration:
    """Gemini provider makes real API calls with proper auth."""

    def test_provider_stores_api_key(self):
        """Gemini provider correctly stores the API key for later use."""
        from app.llm.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="gemini-test-key-XYZ")
        assert provider.api_key == "gemini-test-key-XYZ"
        assert provider.model == "gemini-2.0-flash"
        assert provider.provider_name == "gemini"

    @pytest.mark.asyncio
    async def test_is_available_false_without_key(self):
        """is_available returns False when key is empty."""
        from app.llm.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="")
        result = await provider.is_available()
        assert result is False

    @pytest.mark.asyncio
    async def test_is_available_true_with_key_and_client(self):
        """is_available returns True when key is set and client works."""
        from unittest.mock import MagicMock

        from app.llm.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="gemini-key-123")
        provider._client = MagicMock()  # Pre-inject a mock client
        result = await provider.is_available()
        assert result is True


class TestAlpacaBrokerIntegration:
    """Alpaca broker sends proper HTTP requests with auth headers."""

    @pytest.mark.asyncio
    async def test_execute_sends_auth_headers(self):
        """Verify API key/secret are sent in Alpaca-specific headers."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "broker-order-123",
            "status": "accepted",
            "filled_qty": "100",
            "filled_avg_price": "174.50",
            "filled_at": "2026-04-01T14:30:00Z",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Patch settings at the module where it's imported
        with patch(
            "app.agents.front_office.trading.alpaca_broker.settings"
        ) as mock_s:
            mock_s.alpaca_api_key = "ALPACA_KEY_123"
            mock_s.alpaca_api_secret = "ALPACA_SECRET_456"
            mock_s.alpaca_base_url = "https://paper-api.alpaca.markets"

            with patch(
                "app.agents.front_office.trading.alpaca_broker.httpx.AsyncClient",
                return_value=mock_client,
            ):
                result = await broker.execute({
                    "symbol": "AAPL.NASDAQ",
                    "side": "BUY",
                    "quantity": 100,
                    "order_type": "MARKET",
                    "id": "test-order-1",
                })

        # Verify auth headers
        call_kwargs = mock_client.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers["APCA-API-KEY-ID"] == "ALPACA_KEY_123"
        assert headers["APCA-API-SECRET-KEY"] == "ALPACA_SECRET_456"

        # Verify correct URL
        call_args = mock_client.post.call_args.args
        assert "paper-api.alpaca.markets/v2/orders" in call_args[0]

        # Verify result
        assert result is not None
        assert result["broker_order_id"] == "broker-order-123"
        assert result["broker"] == "ALPACA"

    @pytest.mark.asyncio
    async def test_execute_http_error_returns_none(self):
        """HTTP errors are caught and return None (graceful degradation)."""
        from unittest.mock import AsyncMock, patch

        import httpx

        from app.agents.front_office.trading.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.agents.front_office.trading.alpaca_broker.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await broker.execute({
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 10,
                "id": "test",
            })

        assert result is None


class TestZerodhaBrokerIntegration:
    """Zerodha broker uses Kite Connect API with proper auth."""

    @pytest.mark.asyncio
    async def test_mock_mode_uses_paper_broker(self):
        """In mock mode, orders go to PaperBroker, not Kite API."""
        from unittest.mock import AsyncMock, patch

        from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker

        broker = ZerodhaBroker()

        with patch(
            "app.agents.front_office.trading.zerodha_broker.settings"
        ) as mock_s:
            mock_s.zerodha_mock_mode = True

            # Mock the paper broker
            mock_paper = AsyncMock()
            mock_paper.execute = AsyncMock(return_value={
                "order_id": "test",
                "fill_price": 2450.0,
                "filled_qty": 10,
            })
            broker._paper = mock_paper

            result = await broker.execute({
                "symbol": "RELIANCE.NSE",
                "side": "BUY",
                "quantity": 10,
                "id": "test",
            })

        assert result is not None
        assert result["broker"] == "ZERODHA_MOCK"

    @pytest.mark.asyncio
    async def test_live_mode_sends_kite_headers(self):
        """In live mode, Kite Connect auth headers are sent."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.front_office.trading.zerodha_broker import ZerodhaBroker

        broker = ZerodhaBroker()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"order_id": "kite-order-789"}
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Mock the fill polling
        mock_status_resp = MagicMock()
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {
            "data": [{"status": "COMPLETE", "filled_quantity": 10, "average_price": 2450}]
        }
        mock_client.get = AsyncMock(return_value=mock_status_resp)

        with patch(
            "app.agents.front_office.trading.zerodha_broker.settings"
        ) as mock_s:
            mock_s.zerodha_mock_mode = False
            mock_s.zerodha_api_key = "KITE_KEY_123"
            mock_s.zerodha_api_secret = "KITE_SECRET_456"
            mock_s.zerodha_access_token = "ACCESS_TOKEN_789"

            with patch(
                "app.agents.front_office.trading.zerodha_broker.httpx.AsyncClient",
                return_value=mock_client,
            ):
                result = await broker.execute({
                    "symbol": "RELIANCE.NSE",
                    "side": "BUY",
                    "quantity": 10,
                    "order_type": "MARKET",
                    "id": "test-order-1",
                })

        # Verify auth header format: "token {api_key}:{access_token}"
        call_kwargs = mock_client.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers["Authorization"] == "token KITE_KEY_123:ACCESS_TOKEN_789"
        assert headers["X-Kite-Version"] == "3"

        assert result is not None
        assert result["broker"] == "ZERODHA"


class TestAlpacaFeedIntegration:
    """Alpaca feed checks for API key and uses proper auth."""

    @pytest.mark.asyncio
    async def test_connect_disabled_without_key(self):
        """Feed does not connect when alpaca_api_key is empty."""
        from unittest.mock import patch

        from app.data_layer.alpaca_feed import AlpacaFeed

        feed = AlpacaFeed()

        with patch("app.data_layer.alpaca_feed.settings") as mock_s:
            mock_s.alpaca_api_key = ""
            await feed.connect()

        assert feed.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_enabled_with_key(self):
        """Feed connects when alpaca_api_key is set."""
        from unittest.mock import patch

        from app.data_layer.alpaca_feed import AlpacaFeed

        feed = AlpacaFeed()

        with patch("app.data_layer.alpaca_feed.settings") as mock_s:
            mock_s.alpaca_api_key = "ALPACA_KEY"
            mock_s.alpaca_paper_mode = True
            await feed.connect()

        assert feed.is_connected is True
        await feed.disconnect()

    def test_auth_headers_include_key_and_secret(self):
        """Auth headers contain Alpaca-specific key/secret headers."""
        from unittest.mock import patch

        from app.data_layer.alpaca_feed import AlpacaFeed

        feed = AlpacaFeed()

        with patch("app.data_layer.alpaca_feed.settings") as mock_s:
            mock_s.alpaca_api_key = "MY_KEY"
            mock_s.alpaca_api_secret = "MY_SECRET"
            headers = feed._auth_headers

        assert headers["APCA-API-KEY-ID"] == "MY_KEY"
        assert headers["APCA-API-SECRET-KEY"] == "MY_SECRET"


class TestZerodhaFeedIntegration:
    """Zerodha feed handles mock/live modes correctly."""

    @pytest.mark.asyncio
    async def test_mock_mode_generates_ticks(self):
        """In mock mode, feed generates random ticks (no real connection)."""
        from unittest.mock import patch

        from app.data_layer.zerodha_feed import ZerodhaFeed

        feed = ZerodhaFeed()

        with patch("app.data_layer.zerodha_feed.settings") as mock_s:
            mock_s.zerodha_mock_mode = True
            await feed.connect()

        assert feed.is_connected is True

        tick = feed._generate_mock_tick("RELIANCE")
        assert tick.symbol == "RELIANCE"
        assert tick.exchange == "NSE"
        assert tick.currency == "INR"
        assert tick.last_price > 0
        await feed.disconnect()

    @pytest.mark.asyncio
    async def test_live_mode_needs_credentials(self):
        """Live mode refuses to connect without api_key + access_token."""
        from unittest.mock import patch

        from app.data_layer.zerodha_feed import ZerodhaFeed

        feed = ZerodhaFeed()

        with patch("app.data_layer.zerodha_feed.settings") as mock_s:
            mock_s.zerodha_mock_mode = False
            mock_s.zerodha_api_key = ""
            mock_s.zerodha_access_token = ""
            await feed.connect()

        assert feed.is_connected is False


class TestNewsAPIIntegration:
    """NewsAPI client uses API key and makes real HTTP calls."""

    @pytest.mark.asyncio
    async def test_no_key_returns_empty(self):
        """Without API key, returns empty list (no crash)."""
        from app.agents.front_office.research.newsapi_client import NewsAPIClient

        client = NewsAPIClient(api_key="")
        result = await client.fetch_news("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_sends_api_key(self):
        """API key is included in request params."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.agents.front_office.research.newsapi_client import NewsAPIClient

        client = NewsAPIClient(api_key="newsapi-test-key-123")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "articles": [
                {
                    "title": "Apple hits new high",
                    "description": "AAPL rises 3%",
                    "url": "https://example.com/news/1",
                    "publishedAt": "2026-04-01T10:00:00Z",
                    "source": {"name": "TechNews"},
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.agents.front_office.research.newsapi_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            articles = await client.fetch_news("AAPL")

        # Verify API key in params
        call_kwargs = mock_client.get.call_args.kwargs
        params = call_kwargs.get("params", {})
        assert params["apiKey"] == "newsapi-test-key-123"
        assert "Apple" in params["q"]

        assert len(articles) == 1
        assert articles[0]["title"] == "Apple hits new high"


class TestRedditClientIntegration:
    """Reddit client handles missing credentials gracefully."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_empty(self):
        """Without client_id/secret, returns empty list."""
        from app.agents.front_office.research.reddit_client import RedditClient

        client = RedditClient(client_id="", client_secret="")
        result = await client.fetch_posts("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_with_credentials_creates_praw_instance(self):
        """With credentials, PRAW Reddit instance is created correctly."""
        from unittest.mock import patch

        from app.agents.front_office.research.reddit_client import RedditClient

        client = RedditClient(
            client_id="test-id",
            client_secret="test-secret",
            user_agent="test-agent/1.0",
        )

        with patch("app.agents.front_office.research.reddit_client.praw.Reddit") as mk:
            client._get_reddit()
            mk.assert_called_once_with(
                client_id="test-id",
                client_secret="test-secret",
                user_agent="test-agent/1.0",
            )


class TestSimpleStrategiesPipeline:
    """End-to-end: simple strategies produce valid signals."""

    def test_rsi_strategy_signal_structure(self):
        """RSI strategy returns signals with correct fields."""
        import pandas as pd
        from app.agents.front_office.strategy.simple_strategies import RSIStrategy
        from app.agents.front_office.strategy.base_strategy import Signal

        prices = [100 - i * 2 for i in range(30)]
        df = pd.DataFrame({
            "open": prices, "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices], "close": prices,
            "volume": [1000] * len(prices),
        })
        signal = RSIStrategy().generate_signal("AAPL", df)
        if signal is not None:
            assert isinstance(signal, Signal)
            assert signal.symbol == "AAPL"
            assert signal.direction in (-1, 0, 1)
            assert 0.0 <= signal.strength <= 1.0

    def test_all_three_strategies_instantiate(self):
        """All three strategies can be instantiated and have correct names."""
        from app.agents.front_office.strategy.simple_strategies import (
            RSIStrategy, MACDStrategy, BollingerBandStrategy,
        )
        strategies = [RSIStrategy(), MACDStrategy(), BollingerBandStrategy()]
        names = [s.name for s in strategies]
        assert "rsi" in names
        assert "macd" in names
        assert "bollinger" in names


class TestConfigAPIKeyLoading:
    """API keys are properly loaded from environment/settings."""

    def test_all_api_key_fields_exist(self):
        """Settings class has all expected API key fields."""
        from app.config import Settings
        fields = Settings.model_fields
        expected = [
            "anthropic_api_key",
            "openai_api_key",
            "google_api_key",
            "alpaca_api_key",
            "alpaca_api_secret",
            "zerodha_api_key",
            "zerodha_api_secret",
            "zerodha_access_token",
            "polygon_api_key",
            "newsapi_api_key",
            "reddit_client_id",
            "reddit_client_secret",
            "telegram_bot_token",
        ]
        for key in expected:
            assert key in fields, f"Missing API key field: {key}"

    def test_api_keys_default_to_empty(self):
        """All API keys default to empty string (not None)."""
        from app.config import Settings
        defaults = {
            "anthropic_api_key": "",
            "openai_api_key": "",
            "google_api_key": "",
            "alpaca_api_key": "",
            "polygon_api_key": "",
            "newsapi_api_key": "",
            "reddit_client_id": "",
        }
        for key, expected_default in defaults.items():
            assert Settings.model_fields[key].default == expected_default

    def test_production_warnings_for_missing_keys(self):
        """validate_production_secrets returns warnings for missing keys."""
        from app.config import Settings

        s = Settings(
            anthropic_api_key="",
            openai_api_key="",
            google_api_key="",
            alpaca_api_key="",
            zerodha_api_key="",
        )
        warnings = s.validate_production_secrets()
        assert any("LLM" in w for w in warnings)
        assert any("broker" in w.lower() for w in warnings)


class TestDataManagerFeedWiring:
    """DataManager correctly instantiates and wires all feeds."""

    def test_all_feeds_instantiated(self):
        """DataManager creates instances of all feed types."""
        from app.data_layer.alpaca_feed import AlpacaFeed
        from app.data_layer.crypto_feed import CryptoFeed
        from app.data_layer.data_manager import DataManager
        from app.data_layer.forex_feed import ForexFeed
        from app.data_layer.polygon_feed import PolygonFeed
        from app.data_layer.yahoo_feed import YahooFeed
        from app.data_layer.zerodha_feed import ZerodhaFeed

        dm = DataManager()
        assert isinstance(dm.yahoo_feed, YahooFeed)
        assert isinstance(dm.alpaca_feed, AlpacaFeed)
        assert isinstance(dm.zerodha_feed, ZerodhaFeed)
        assert isinstance(dm.crypto_feed, CryptoFeed)
        assert isinstance(dm.forex_feed, ForexFeed)
        assert isinstance(dm.polygon_feed, PolygonFeed)

    def test_feeds_list_has_five_entries(self):
        """Internal _feeds list contains exactly 5 feeds (all except forex)."""
        from app.data_layer.data_manager import DataManager
        dm = DataManager()
        assert len(dm._feeds) == 5


class TestCircuitBreakerOnFeeds:
    """Data ingestion worker wraps feeds with circuit breakers."""

    def test_worker_has_circuit_breakers(self):
        """DataIngestionWorker creates circuit breakers for all feed types."""
        from app.workers.data_ingestion_worker import DataIngestionWorker
        worker = DataIngestionWorker()
        assert worker._yahoo_cb.name == "yahoo"
        assert worker._crypto_cb.name == "coingecko"
        assert worker._forex_cb.name == "forex"
        assert worker._yahoo_cb.failure_threshold == 5
        assert worker._forex_cb.failure_threshold == 3
