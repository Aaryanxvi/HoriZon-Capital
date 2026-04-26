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

    # Skip cash and position writes for this test — focus on recursion only
    async def noop(*a, **kw):
        pass

    monkeypatch.setattr(agent.order_manager, "update_position", noop)
    monkeypatch.setattr(agent, "_update_cash_balance", noop)
    monkeypatch.setattr(agent.order_manager, "record_fill", noop)
    monkeypatch.setattr(agent.order_manager, "update_status", noop)

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
