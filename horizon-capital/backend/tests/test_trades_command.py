"""Tests for the `trades` REPL command (_cmd_trades)."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

os.environ["STORAGE_BACKEND"] = "LOCAL"
os.environ["SYSTEM_MODE"] = "PAPER_TRADING"
os.environ["APP_DEBUG"] = "false"


@pytest_asyncio.fixture
async def runtime():
    from app.core.runtime import shutdown, startup
    await startup()
    yield
    await shutdown()


async def _seed_fills(n: int, *, orphan: int = 0, base_time: datetime | None = None) -> list[str]:
    """Insert n (order, fill) pairs and orphan fills with no parent order."""
    from sqlalchemy import text

    from app.core.runtime import get_session_factory

    base_time = base_time or datetime.now(UTC)
    fill_ids: list[str] = []
    sf = get_session_factory()
    async with sf() as session:
        for i in range(n):
            oid = str(uuid.uuid4())
            fid = str(uuid.uuid4())
            ts = base_time - timedelta(minutes=i)
            await session.execute(
                text(
                    "INSERT INTO orders (id, symbol, exchange, order_type, side, "
                    "quantity, status, broker, mode, created_at, updated_at) "
                    "VALUES (:id, :sym, 'NASDAQ', 'MARKET', :side, :q, 'FILLED', "
                    "'paper', 'PAPER_TRADING', :now, :now)"
                ),
                {"id": oid, "sym": "AAPL", "side": "BUY" if i % 2 == 0 else "SELL",
                 "q": 10.0, "now": ts},
            )
            await session.execute(
                text(
                    "INSERT INTO fills (id, order_id, filled_qty, fill_price, "
                    "commission, slippage, filled_at, created_at, updated_at) "
                    "VALUES (:id, :oid, :q, :p, :c, :s, :ts, :ts, :ts)"
                ),
                {"id": fid, "oid": oid, "q": 10.0, "p": 150.25,
                 "c": 1.50, "s": 0.0123, "ts": ts},
            )
            fill_ids.append(fid)
        for i in range(orphan):
            fid = str(uuid.uuid4())
            ts = base_time - timedelta(hours=1, minutes=i)
            await session.execute(
                text(
                    "INSERT INTO fills (id, order_id, filled_qty, fill_price, "
                    "commission, slippage, filled_at, created_at, updated_at) "
                    "VALUES (:id, :oid, 1, 1, 0, 0, :ts, :ts, :ts)"
                ),
                {"id": fid, "oid": "missing-" + str(i), "ts": ts},
            )
        await session.commit()
    return fill_ids


async def _clear_fills() -> None:
    from sqlalchemy import text

    from app.core.runtime import get_session_factory

    sf = get_session_factory()
    async with sf() as session:
        await session.execute(text("DELETE FROM fills"))
        await session.execute(text("DELETE FROM orders"))
        await session.commit()


class TestTradesCommand:
    @pytest.mark.asyncio
    async def test_all_uppercase_arg_accepted(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(3)

        handler = CommandHandler()
        result = await handler.handle("trades ALL")

        # When "all" (case-insensitive) is passed, header should show "All Trades"
        assert "All Trades" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_all_lowercase_arg_accepted(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(3)

        handler = CommandHandler()
        result = await handler.handle("trades all")

        assert "All Trades" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_page_arg_uppercase(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(3)

        handler = CommandHandler()
        result = await handler.handle("trades PAGE 1")

        # PAGE should be case-insensitive
        assert "Trades (page 1/" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_page_without_number_errors(self, runtime):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("trades page")
        assert "missing page number" in result.lower()

    @pytest.mark.asyncio
    async def test_page_non_integer_errors(self, runtime):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("trades page abc")
        assert "not an integer" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_arg_errors(self, runtime):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("trades wat")
        assert "unknown trades arg" in result.lower()

    @pytest.mark.asyncio
    async def test_orphan_fills_are_listed(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(2, orphan=1)  # 3 total fills, 1 has no parent order

        handler = CommandHandler()
        result = await handler.handle("trades")

        # Header reports 3 total; 3 rows render
        assert "3 total" in result
        row_lines = [ln for ln in result.split("\n") if "AAPL" in ln or "<orphan>" in ln]
        assert len(row_lines) == 3

    @pytest.mark.asyncio
    async def test_commission_and_notional_rendered(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(1)  # commission=1.50, qty=10, price=150.25

        handler = CommandHandler()
        result = await handler.handle("trades")

        assert "Comm" in result           # column header
        assert "1.50" in result           # commission value
        assert "Notional" in result       # column header
        assert "1502.50" in result        # notional: 10 * 150.25

    @pytest.mark.asyncio
    async def test_today_fill_shows_only_time(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(1, base_time=datetime.now(UTC))

        handler = CommandHandler()
        result = await handler.handle("trades")

        today_iso = datetime.now(UTC).date().isoformat()
        assert today_iso not in result

    @pytest.mark.asyncio
    async def test_old_fill_shows_date(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        old = datetime.now(UTC) - timedelta(days=3)
        await _seed_fills(1, base_time=old)

        handler = CommandHandler()
        result = await handler.handle("trades")

        assert old.date().strftime("%m-%d") in result

    @pytest.mark.asyncio
    async def test_all_renders_every_fill(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(150)

        handler = CommandHandler()
        result = await handler.handle("trades all")

        assert "All Trades (150)" in result
        row_lines = [ln for ln in result.split("\n") if "AAPL" in ln]
        assert len(row_lines) == 150

    @pytest.mark.asyncio
    async def test_overflow_page_clamps_to_last(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(25)  # 2 pages at page_size=20

        handler = CommandHandler()
        result = await handler.handle("trades page 99")

        assert "page 2/2" in result
        assert "clamped" in result.lower()

    @pytest.mark.asyncio
    async def test_db_error_is_logged(self, runtime, monkeypatch):
        import app.core.runtime as rt
        from app.tui.commands import CommandHandler

        original = rt.get_session_factory

        def _bad_factory():
            raise RuntimeError("db is on fire")

        monkeypatch.setattr(rt, "get_session_factory", _bad_factory)

        handler = CommandHandler()
        result = await handler.handle("trades")

        monkeypatch.setattr(rt, "get_session_factory", original)

        assert "trades failed" in result.lower()


    @pytest.mark.asyncio
    async def test_db_error_logged_and_returned(self, runtime, monkeypatch, caplog):
        import logging

        from app.core import runtime as rt
        from app.tui.commands import CommandHandler

        def _bad_factory():
            def _ctx():
                raise RuntimeError("db is on fire")
            return _ctx

        monkeypatch.setattr(rt, "get_session_factory", _bad_factory)

        handler = CommandHandler()
        with caplog.at_level(logging.ERROR):
            result = await handler.handle("trades")

        assert "trades failed" in result.lower()
        assert any(
            "trades_command_failed" in rec.getMessage() or
            "trades_command_failed" in str(rec.args)
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_help_banner_documents_trades(self, runtime):
        from app.tui.commands import CommandHandler

        handler = CommandHandler()
        result = await handler.handle("help")

        assert "trades" in result
        assert "page" in result
        assert "newest first" in result.lower()

    @pytest.mark.asyncio
    async def test_count_matches_listing(self, runtime):
        from app.tui.commands import CommandHandler

        await _clear_fills()
        await _seed_fills(7)

        handler = CommandHandler()
        result = await handler.handle("trades")

        assert "7 total" in result
        row_lines = [ln for ln in result.split("\n") if "AAPL" in ln]
        assert len(row_lines) == 7
