"""Comprehensive system audit script for Horizon Capital."""

import asyncio
import importlib
import os
import pkgutil
import sys
import io
import time
import traceback

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

results = {}


def section(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


# 1. MODULE IMPORTS
section("MODULE IMPORT TEST")
import app

errs = []
count = 0
for importer, modname, ispkg in pkgutil.walk_packages(app.__path__, prefix="app."):
    try:
        importlib.import_module(modname)
        count += 1
    except Exception as e:
        errs.append(f"{modname}: {type(e).__name__}: {e}")
print(f"Modules imported: {count}")
for e in errs:
    print(f"  IMPORT ERROR: {e}")
results["imports"] = {"ok": count, "errors": errs}

# 2. CONFIG MODES
section("CONFIG MODE TESTS")
for mode in ["PAPER_TRADING", "HUMAN_APPROVAL", "FULLY_AUTONOMOUS"]:
    for cio in ["HUMAN", "AI"]:
        os.environ["SYSTEM_MODE"] = mode
        os.environ["CIO_MODE"] = cio
        try:
            if "app.config" in sys.modules:
                del sys.modules["app.config"]
            from app.config import Settings
            s = Settings()
            print(f"  {mode} + {cio}: OK")
        except Exception as e:
            print(f"  {mode} + {cio}: ERROR - {e}")
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"
os.environ["CIO_MODE"] = "HUMAN"

# 3. RUNTIME STARTUP/SHUTDOWN
section("RUNTIME STARTUP/SHUTDOWN")


async def test_runtime():
    from app.core.runtime import startup, shutdown, get_bus, get_session_factory

    t0 = time.time()
    await startup(headless=True)
    startup_time = time.time() - t0
    print(f"  startup(): {startup_time:.3f}s")

    bus = get_bus()
    print(f"  bus: {type(bus).__name__}")

    sf = get_session_factory()
    print(f"  session_factory: {type(sf).__name__}")

    # Bus roundtrip
    received = []

    async def handler(msg):
        received.append(msg)

    await bus.subscribe("test.*", handler)
    from app.core.messaging import AgentMessage, MessageType

    msg = AgentMessage(
        sender_id="test",
        channel="test.ping",
        message_type=MessageType.SYSTEM,
        payload={"test": True},
    )
    await bus.publish(msg)
    await asyncio.sleep(0.2)
    print(f"  bus roundtrip: {'OK' if received else 'FAILED'}")

    await shutdown()
    print(f"  shutdown(): OK")
    return startup_time


startup_time = asyncio.run(test_runtime())
results["startup_time"] = startup_time

# 4. KV STORE
section("KV STORE")


async def test_kv():
    from app.core.kv_store import get_kv_store

    kv = get_kv_store()

    await kv.set("test:key", "value123")
    val = await kv.get("test:key")
    print(f"  set/get: {'OK' if val == 'value123' else 'FAILED'}")

    await kv.set("test:ttl", "expire", ex=1)
    val1 = await kv.get("test:ttl")
    time.sleep(1.5)
    val2 = await kv.get("test:ttl")
    print(f"  TTL: {'OK' if val1 == 'expire' and val2 is None else 'FAILED'}")

    await kv.hset("test:hash", {"f1": "v1"})
    await kv.hset("test:hash", {"f2": "v2"})
    hvals = await kv.hgetall("test:hash")
    print(f"  hash: {'OK' if hvals.get('f1') == 'v1' else 'FAILED'}")

    await kv.delete("test:key")
    await kv.delete("test:hash")
    print("  cleanup: OK")


asyncio.run(test_kv())

# 5. SQLITE TABLES
section("SQLITE STORAGE")


async def test_sqlite():
    from app.core.runtime import startup, shutdown, get_session_factory
    from sqlalchemy import text

    await startup(headless=True)
    sf = get_session_factory()
    async with sf() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        tables = [r[0] for r in result.fetchall()]
        print(f"  Tables: {len(tables)}")
        for t in tables:
            try:
                result = await session.execute(text(f'SELECT COUNT(*) FROM "{t}"'))
                cnt = result.scalar()
                print(f"    {t}: {cnt} rows")
            except Exception as e:
                print(f"    {t}: ERROR - {e}")
    await shutdown()


asyncio.run(test_sqlite())

# 6. IMPORT TIMING
section("IMPORT TIMING")
t0 = time.time()
from app.tui.dashboard import TerminalDashboard  # noqa: E402

t1 = time.time()
from app.workers.agent_orchestrator import AgentOrchestrator  # noqa: E402

t2 = time.time()
from app.tui.commands import CommandHandler  # noqa: E402

t3 = time.time()
print(f"  Dashboard: {t1-t0:.3f}s")
print(f"  Orchestrator: {t2-t1:.3f}s")
print(f"  Commands: {t3-t2:.3f}s")
print(f"  Total: {t3-t0:.3f}s")

# 7. LLM REGISTRY
section("LLM PROVIDER REGISTRY")
from app.llm.provider_registry import provider_registry  # noqa: E402

provider_registry.auto_register_from_settings()
available = provider_registry.list_available()
print(f"  Available: {available}")
for p in available:
    prov = provider_registry.get_provider(p)
    print(f"    {p}: {type(prov).__name__}, available={prov.is_available()}")

# 8. CIRCUIT BREAKER
section("CIRCUIT BREAKER")


async def test_cb():
    from app.core.resilience import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1)
    print(f"  Initial: {cb.state}")
    for i in range(4):
        try:
            async with cb:
                raise ValueError("test")
        except Exception:
            pass
    print(f"  After 4 failures: {cb.state}")
    time.sleep(1.1)
    print(f"  After recovery: {cb.state}")


asyncio.run(test_cb())

# 9. DASHBOARD RENDER
section("DASHBOARD RENDER")
dash = TerminalDashboard()
dash.update_watchlist({"symbol": "AAPL.NASDAQ", "price": 178.5, "change_pct": 1.2})
dash.update_watchlist({"symbol": "BTC-USD", "price": 67420.0, "change_pct": 2.1})
dash.update_watchlist({"symbol": "RELIANCE.NSE", "price": 2847.5, "change_pct": -0.3})
dash.update_portfolio({
    "nav": 1024350.0,
    "cash": 241000.0,
    "positions": [
        {"symbol": "AAPL.NASDAQ", "qty": 100, "unrealized_pnl": 500.0},
        {"symbol": "BTC-USD", "qty": 0.5, "unrealized_pnl": 840.0},
    ],
})
dash.update_risk({
    "var_95": 0.018, "var_99": 0.024, "max_drawdown": 3.5,
    "current_drawdown": 1.0, "sharpe_30d": 1.5,
})
dash.add_pending_order({
    "order_id": "ORD-1", "side": "BUY", "symbol": "AAPL", "quantity": 50, "status": "PENDING",
})
dash.add_alert({"severity": "WARNING", "title": "Test alert"})
dash.update_agent_status("strategy-agent-1", {
    "status": "ANALYZING", "department": "front_office",
    "current_task": "momentum scan AAPL",
})

from rich.console import Console  # noqa: E402

c = Console(width=140, force_terminal=True, no_color=True)
try:
    layout = dash.build_layout()
    with c.capture() as cap:
        c.print(layout)
    output = cap.get()
    panels = ["Agents", "Watchlist", "Portfolio", "Risk", "Pending", "Trade History"]
    found = [p for p in panels if p in output]
    print(f"  Rendered: {len(output)} chars, {len(found)}/6 panels")
    if len(found) < 6:
        print(f"  MISSING: {[p for p in panels if p not in output]}")
    else:
        print("  All panels present: OK")
except Exception as e:
    print(f"  RENDER ERROR: {e}")

# 10. ORCHESTRATOR
section("ORCHESTRATOR + ALL AGENTS")


async def test_orch():
    from app.core.runtime import startup, shutdown, get_bus

    await startup(headless=True)
    bus = get_bus()
    orch = AgentOrchestrator(bus=bus)
    try:
        await orch.start_all()
        statuses = orch.get_agent_statuses()
        depts = orch.get_department_statuses()
        print(f"  Agents registered: {len(statuses)}")
        for d in depts:
            healthy = "OK" if d.get("healthy", True) else "UNHEALTHY"
            print(
                f"    {d['display_name']}: "
                f"{d['agents_running']}/{d['agents_total']} [{healthy}]"
            )

        failed = [
            aid
            for aid, info in statuses.items()
            if info.get("state") == "FAILED" or info.get("status") == "FAILED"
        ]
        if failed:
            print(f"  FAILED agents: {failed}")
        else:
            print("  All agents healthy")

        # List all agents
        for aid in sorted(statuses.keys()):
            info = statuses[aid]
            state = info.get("state", info.get("status", "?"))
            dept = info.get("department", "?")
            print(f"    {aid}: {state} ({dept})")

        await asyncio.sleep(2)
        await orch.stop_all()
        print("  stop_all(): OK")
    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
    await shutdown()


asyncio.run(test_orch())

# 11. WORKER INDIVIDUAL TESTS
section("WORKER STARTUP TESTS")


async def test_workers():
    from app.core.runtime import startup, shutdown, get_bus

    await startup(headless=True)
    bus = get_bus()

    workers_to_test = [
        ("DataIngestionWorker", "app.workers.data_ingestion_worker", "DataIngestionWorker", {}),
        ("FeatureComputationWorker", "app.workers.feature_computation_worker",
         "FeatureComputationWorker", {}),
        ("PerformanceWorker", "app.workers.performance_worker", "PerformanceWorker", {}),
        ("PositionMonitorWorker", "app.workers.position_worker", "PositionMonitorWorker", {}),
        ("MacroFactorWorker", "app.workers.macro_worker", "MacroFactorWorker", {"bus": bus}),
    ]

    for name, mod_path, cls_name, kwargs in workers_to_test:
        try:
            m = importlib.import_module(mod_path)
            cls = getattr(m, cls_name)
            w = cls(**kwargs)
            task = asyncio.create_task(w.run(), name=name)
            await asyncio.sleep(1)
            if task.done():
                exc = task.exception() if not task.cancelled() else "CANCELLED"
                print(f"  {name}: CRASHED - {exc}")
            else:
                print(f"  {name}: RUNNING OK")
                await w.stop()
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception as e:
            print(f"  {name}: FAILED TO START - {e}")

    await shutdown()


asyncio.run(test_workers())

# 12. MEMORY USAGE
section("MEMORY USAGE")
# resource module not available on Windows
try:
    import psutil
    proc = psutil.Process()
    mem = proc.memory_info()
    print(f"  RSS: {mem.rss / 1024 / 1024:.1f} MB")
    print(f"  VMS: {mem.vms / 1024 / 1024:.1f} MB")
except ImportError:
    print("  psutil not available, skipping memory measurement")

print(f"\n{'='*60}")
print("  ALL DIAGNOSTICS COMPLETE")
print(f"{'='*60}")
