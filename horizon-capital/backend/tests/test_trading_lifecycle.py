import asyncio
import pytest
import pytest_asyncio
from app.agents.front_office.trading.execution_agent import ExecutionAgent
from app.core.memory_bus import MemoryBus
from app.core.messaging import AgentMessage, MessageType


@pytest.mark.asyncio
async def test_execution_does_not_recurse_on_own_tracked_emit(monkeypatch):
    bus = MemoryBus()
    await bus.start_listening()

    agent = ExecutionAgent(bus=bus)
    await agent._subscribe()

    created_orders = []
    original_create = agent.order_manager.create_order

    async def spy_create(data):
        created_orders.append(data)
        return await original_create(data)

    monkeypatch.setattr(agent.order_manager, "create_order", spy_create)

    # Stub broker so it always returns a fill
    async def fake_execute(order):
        return {
            "filled_qty": order["quantity"],
            "fill_price": 100.0,
            "commission": 0.0,
            "slippage": 0.0,
        }

    monkeypatch.setattr(agent.paper_broker, "execute", fake_execute)

    # Short-circuit the atomic execute path — this test only verifies that the
    # bus delivers ORDER_NEW exactly once (no self-delivery via tracked emit).
    async def noop_execute(order):
        pass

    monkeypatch.setattr(agent, "_execute_order", noop_execute)

    # Send ONE order
    msg = AgentMessage(
        sender_id="test",
        channel="horizon.execution.order.new",
        message_type=MessageType.ORDER_NEW,
        payload={
            "symbol": "AAPL", "exchange": "NASDAQ",
            "side": "BUY", "quantity": 10,
            "order_type": "MARKET", "signal_id": "sig-1",
        },
    )
    await bus.publish(msg)
    await asyncio.sleep(0.5)  # let dispatch settle

    assert len(created_orders) == 1, (
        f"Expected exactly 1 order created, got {len(created_orders)} "
        "(recursion still happening)"
    )

    await bus.stop()


@pytest_asyncio.fixture
async def runtime():
    """Fixture: initialize runtime for tests that need startup/shutdown."""
    from app.core.runtime import startup, shutdown
    await startup()
    yield
    await shutdown()


@pytest.mark.asyncio
async def test_sizer_targets_weight_not_fixed_slot(monkeypatch, runtime):
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent
    from app.core.memory_bus import MemoryBus
    from app.core.kv_store import get_kv_store
    from app.config import settings

    bus = MemoryBus()
    agent = PortfolioAgent(bus=bus)

    # Raise the position cap to allow 15% target weight
    monkeypatch.setattr(settings, "risk_max_position_pct", 25.0)

    # NAV 100k cash, no positions
    kv = get_kv_store()
    await kv.set("horizon:cash:usd", "100000")
    await kv.set("horizon:cash:inr", "0")
    await kv.set("horizon:price:AAPL", "100")

    sizing = await agent._compute_position_size(
        symbol="AAPL", direction=1, exchange="NASDAQ",
        target_weight=0.15,
    )

    # 15% of 100k = $15k. At $100/share = 150 shares.
    assert sizing["quantity"] == 150, (
        f"Expected 150 shares for 15% target, got {sizing['quantity']}"
    )
    assert sizing["allocation_usd"] == pytest.approx(15000.0, abs=1.0)


@pytest.mark.asyncio
async def test_portfolio_recomputes_nav_on_order_fill(monkeypatch, runtime):
    from app.agents.front_office.portfolio.portfolio_agent import PortfolioAgent

    bus = MemoryBus()
    await bus.start_listening()
    agent = PortfolioAgent(bus=bus)
    await agent._subscribe()

    called = {"count": 0}
    async def fake_snapshot():
        called["count"] += 1
    monkeypatch.setattr(agent, "_update_snapshot", fake_snapshot)

    await bus.publish(AgentMessage(
        sender_id="exec", channel="horizon.execution.order.fill",
        message_type=MessageType.ORDER_FILL,
        payload={"order_id": "x", "symbol": "AAPL", "side": "BUY",
                 "filled_qty": 10, "fill_price": 100.0},
    ))
    await asyncio.sleep(0.3)
    assert called["count"] == 1
    await bus.stop()
