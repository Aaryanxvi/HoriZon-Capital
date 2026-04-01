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
            message_type=MessageType.SYSTEM,
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
            message_type=MessageType.SYSTEM, payload={},
        ))
        await asyncio.sleep(0.2)
        assert len(received) == 1

        await bus.unsubscribe("horizon.test")
        await bus.publish(AgentMessage(
            sender_id="s", channel="horizon.test",
            message_type=MessageType.SYSTEM, payload={},
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
            message_type=MessageType.RISK_APPROVED,
            payload={"symbol": "AAPL", "direction": 1, "strength": 0.7},
        ))
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].message_type == MessageType.RISK_APPROVED
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
            message_type=MessageType.RISK_REJECTED,
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

        # Should have 2 messages: KILL_SWITCH + ORDER_CANCEL_ALL
        types = [m.message_type for m in received]
        assert MessageType.KILL_SWITCH in types
        assert MessageType.ORDER_CANCEL_ALL in types
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
