"""DB-backed cash balance store, transaction-aware.

Cash lives in the ``cash_balances`` SQL table so that writes can participate
in the same transaction as fills + positions (atomicity). The KV store key
``horizon:cash:<currency>`` is updated as a post-commit cache for legacy
readers; the source of truth is this table.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("core.cash")

_VALID_CURRENCIES = {"USD", "INR"}


def _check(currency: str) -> None:
    if currency not in _VALID_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency!r}")


async def get_cash(session: AsyncSession, currency: str) -> float:
    """Read the cash balance for ``currency`` using the caller's session."""
    _check(currency)
    result = await session.execute(
        text("SELECT amount FROM cash_balances WHERE currency = :c"),
        {"c": currency},
    )
    row = result.fetchone()
    return float(row.amount) if row else 0.0


async def set_cash(session: AsyncSession, currency: str, amount: float) -> None:
    """Upsert the cash balance for ``currency`` using the caller's session.

    The caller owns commit/rollback. The KV mirror is written by
    ``mirror_to_kv`` AFTER the caller commits.
    """
    _check(currency)
    await session.execute(
        text("""
            INSERT INTO cash_balances (currency, amount, updated_at)
            VALUES (:c, :a, CURRENT_TIMESTAMP)
            ON CONFLICT(currency) DO UPDATE
            SET amount = :a, updated_at = CURRENT_TIMESTAMP
        """),
        {"c": currency, "a": float(amount)},
    )


async def adjust_cash(session: AsyncSession, currency: str, delta: float) -> float:
    """Read-modify-write cash within a single SQL statement and return the new total.

    LOCAL mode (SQLite): safe under concurrent calls because SQLite serialises
    all writers at the database level, so the INSERT...ON CONFLICT...SET
    amount = amount + :d sequence is atomic.

    POSTGRES: this function alone is NOT safe. Postgres allows concurrent
    sessions; without an explicit ``SERIALIZABLE`` transaction or a
    ``SELECT ... FOR UPDATE`` lock, two concurrent ``adjust_cash`` calls can
    lose updates. Wrap accordingly when porting to Postgres.

    Treats a missing row for ``currency`` as a balance of 0 — the INSERT
    branch seeds the row at exactly ``delta`` (which can be negative).
    """
    _check(currency)
    await session.execute(
        text("""
            INSERT INTO cash_balances (currency, amount, updated_at)
            VALUES (:c, :d, CURRENT_TIMESTAMP)
            ON CONFLICT(currency) DO UPDATE
            SET amount = cash_balances.amount + :d,
                updated_at = CURRENT_TIMESTAMP
        """),
        {"c": currency, "d": float(delta)},
    )
    return await get_cash(session, currency)


async def mirror_to_kv(currency: str, amount: float) -> None:
    """Sync the cash balance to the KV cache for legacy readers.

    Call AFTER the SQL transaction commits. Failures are logged, not raised:
    KV is a cache, the SQL row is the source of truth.
    """
    _check(currency)
    try:
        from app.core.kv_store import get_kv_store
        kv = get_kv_store()
        key = f"horizon:cash:{currency.lower()}"
        await kv.set(key, str(round(float(amount), 2)))
    except Exception as exc:
        logger.warning("cash_kv_mirror_failed", currency=currency, error=str(exc))
