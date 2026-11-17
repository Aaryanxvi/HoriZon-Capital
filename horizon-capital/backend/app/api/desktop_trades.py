"""Desktop trade timeline — one order's life from signal to P&L, LOCAL SQLite only.

Mounted at ``/api/desktop/trades``. Read-only, same rules as ``api/desktop.py``.

Links, strongest first (``link`` on each step says which one held):
- ``id``   — a stored foreign key: orders.signal_id -> signals / the bus log
  (agent_messages, where RiskAgent's approved/rejected copy carries signal_id),
  orders.debate_id or debate_sessions.signal_id -> debate_sessions,
  fills.order_id -> orders.
- ``time`` — no id was stored (current DebateAgent does not persist signal_id and
  PortfolioAgent passes debate_id=None outside FULLY_AUTONOMOUS), so the nearest
  debate on the same symbol + side within ``DEBATE_WINDOW`` of the order is shown.
A step that cannot be linked is ``skipped`` (it never happens for this kind of
order) or ``unknown`` (it should exist but nothing recorded it) — never guessed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.desktop import _f, _query

router = APIRouter(prefix="/api/desktop/trades", tags=["desktop"])

DEBATE_WINDOW = timedelta(minutes=15)

# Orders that never came from a strategy signal, so signal/risk/debate cannot exist.
_NO_SIGNAL = {
    "reconcile": "Drift correction by PortfolioAgent — no strategy signal behind it",
    "stop_loss": "Protective stop exit — no strategy signal behind it",
}


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(value: Any) -> str | None:
    dt = _ts(value)
    return dt.isoformat() if dt else None


def _json(raw: Any) -> dict:
    try:
        out = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def _step(key: str, state: str, at: Any = None, link: str | None = None,
          note: str | None = None, **detail: Any) -> dict[str, Any]:
    return {"key": key, "status": state, "at": _iso(at), "link": link,
            "note": note, "detail": detail}


async def _bus(signal_id: str, channel_like: str) -> list[dict[str, Any]]:
    """Bus-log rows (agent_messages) carrying this signal_id, oldest first."""
    return await _query(
        "SELECT channel, payload, created_at FROM agent_messages "
        "WHERE channel LIKE :ch AND json_extract(payload, '$.signal_id') = :sid "
        "ORDER BY created_at",
        {"ch": channel_like, "sid": signal_id},
    )


async def _signal_step(order: dict, bus: list[dict]) -> dict[str, Any]:
    sid = order.get("signal_id")
    strategy = order.get("strategy_name")
    if not sid:
        return _step("signal", "skipped",
                     note=_NO_SIGNAL.get(strategy, "Manual order — no signal behind it"))
    rows = await _query(
        "SELECT direction, strength, confidence, strategy_name, regime, metadata, created_at "
        "FROM signals WHERE signal_id = :sid", {"sid": sid},
    )
    # StrategyAgent emits before it writes the row, so the bus copy can be earlier.
    sig_rows = [b for b in bus
                if b["channel"].startswith(("horizon.signal.", "horizon.risk.approved."))]
    if rows:
        r = rows[0]
        meta = _json(r["metadata"])
        times = [_ts(r["created_at"]), *(_ts(b["created_at"]) for b in sig_rows)]
        at = min(filter(None, times), default=None)
        return _step("signal", "done", at, "id",
                     signal_id=sid, strategy=r["strategy_name"], direction=r["direction"],
                     strength=r["strength"], confidence=r["confidence"], regime=r["regime"],
                     reasoning=meta.get("reasoning"), target_weight=meta.get("target_weight"))
    # Reconcile/stop signals never reach the signals table; RiskAgent's copy does
    # reach the bus log (pruned after agent_messages_retention_days).
    if sig_rows:
        p = _json(sig_rows[0]["payload"])
        return _step("signal", "done", sig_rows[0]["created_at"], "id",
                     note="From the bus log (no signals-table row)",
                     signal_id=sid, strategy=p.get("strategy_name"),
                     direction="BUY" if _f(p.get("direction")) > 0 else "SELL",
                     strength=p.get("strength"),
                     confidence=p.get("confidence"), reasoning=p.get("reasoning"),
                     target_weight=p.get("target_weight"))
    if strategy in _NO_SIGNAL:
        return _step("signal", "skipped", note=_NO_SIGNAL[strategy])
    return _step("signal", "unknown", link=None, signal_id=sid,
                 note="Signal id recorded on the order but no signal row or bus record found")


def _risk_step(order: dict, bus: list[dict]) -> dict[str, Any]:
    for b in bus:
        ch = b["channel"]
        if not ch.startswith(("horizon.risk.approved.", "horizon.risk.rejected.")):
            continue
        p = _json(b["payload"])
        # Same clock as the signal fallback (bus persist time), so the order never inverts.
        at = b["created_at"] or p.get("timestamp")
        if ch.startswith("horizon.risk.rejected."):
            return _step("risk", "blocked", at, "id", decision="REJECTED",
                         violations=p.get("violations") or [])
        exit_ = int(p.get("direction") or 0) < 0
        return _step("risk", "done", at, "id", decision="APPROVED",
                     note="Exits pass the gate for the audit trail only" if exit_ else None)
    if not order.get("signal_id"):
        return _step("risk", "skipped", note="No signal, so RiskAgent never saw it")
    if order.get("strategy_name") in _NO_SIGNAL:
        return _step("risk", "skipped", note="Sized straight to execution, not risk-gated")
    return _step("risk", "unknown",
                 note="No risk decision in the bus log (pruned, or RiskAgent was down)")


async def _debate_step(order: dict) -> dict[str, Any]:
    cols = ("SELECT id, signal_id, proposed_action, status, final_decision, consensus_score, "
            "total_rounds, reason, created_at FROM debate_sessions ")
    row, link = None, None
    if order.get("debate_id"):
        hit = await _query(cols + "WHERE id = :id", {"id": order["debate_id"]})
        row, link = (hit[0], "id") if hit else (None, None)
    if row is None and order.get("signal_id"):
        hit = await _query(cols + "WHERE signal_id = :sid ORDER BY created_at DESC LIMIT 1",
                           {"sid": order["signal_id"]})
        row, link = (hit[0], "id") if hit else (None, None)
    if row is None:
        placed = _ts(order["created_at"])
        near = [
            (abs(dt - placed), d)
            for d in await _query(cols + "WHERE symbol = :sym AND upper(proposed_action) = :side",
                                  {"sym": order["symbol"], "side": order["side"].upper()})
            if (dt := _ts(d["created_at"])) and placed and abs(dt - placed) <= DEBATE_WINDOW
        ]
        if near:
            row, link = min(near, key=lambda x: x[0])[1], "time"
    if row is None:
        if order["side"].upper() == "SELL":
            note = "Exits are never debated"
        elif order.get("strategy_name") in _NO_SIGNAL or not order.get("signal_id"):
            note = "Not a strategy signal, so no debate"
        else:
            note = (f"No debate recorded within {int(DEBATE_WINDOW.total_seconds() // 60)} min"
                    " — binding only in FULLY_AUTONOMOUS")
        return _step("debate", "skipped", note=note)

    votes = await _query(
        "SELECT vote, round_number FROM debate_arguments WHERE session_id = :id",
        {"id": row["id"]},
    )
    last = max((v["round_number"] or 1 for v in votes), default=None)
    tally: dict[str, int] = {}
    for v in votes:
        if (v["round_number"] or 1) == last:
            key = (v["vote"] or "UNKNOWN").upper()
            tally[key] = tally.get(key, 0) + 1
    decision = (row["final_decision"] or row["status"] or "").upper()
    notes = []
    if row.get("signal_id") and order.get("signal_id") and row["signal_id"] != order["signal_id"]:
        notes.append("This debate was opened on a later signal for the same symbol")
    binding = order.get("mode") == "FULLY_AUTONOMOUS"
    if decision != "APPROVED" and not binding:
        notes.append(f"Not binding in {order.get('mode') or 'this mode'} — the order went ahead")
    note = ". ".join(notes) or None
    return _step("debate", "done" if decision == "APPROVED" or not binding else "blocked",
                 row["created_at"], link, note=note,
                 session_id=row["id"], decision=decision or None,
                 consensus=row["consensus_score"], rounds=row["total_rounds"],
                 votes=tally, reason=row["reason"] or None)


async def _sizing_price(order: dict) -> float | None:
    """Price PortfolioAgent sized at (allocation / requested qty), from the ORDER_NEW."""
    if not order.get("signal_id"):
        return None
    rows = await _bus(order["signal_id"], "horizon.execution.order.new")
    if not rows:
        return None
    p = _json(rows[-1]["payload"])
    alloc, qty = _f(p.get("allocation_usd")), _f(p.get("quantity"))
    return alloc / qty if alloc > 0 and qty > 0 else None


@router.get("/{order_id}/timeline")
async def timeline(order_id: str) -> dict[str, Any]:
    found = await _query(
        "SELECT id, symbol, exchange, order_type, side, quantity, limit_price, stop_price, "
        "status, broker, mode, signal_id, debate_id, strategy_name, broker_order_id, "
        "rejection_reason, created_at, updated_at FROM orders WHERE id = :id",
        {"id": order_id},
    )
    if not found:
        raise HTTPException(status_code=404, detail="Order not found")
    order = found[0]
    side = (order["side"] or "").upper()
    sign = 1 if side == "BUY" else -1

    bus = await _bus(order["signal_id"], "horizon.%") if order["signal_id"] else []
    steps = [await _signal_step(order, bus), _risk_step(order, bus), await _debate_step(order)]

    status = (order["status"] or "").upper()
    steps.append(_step(
        "order", "blocked" if status in ("REJECTED", "CANCELLED") else "done",
        order["created_at"], "id",
        side=side, quantity=order["quantity"], order_type=order["order_type"],
        limit_price=order["limit_price"], broker=order["broker"], mode=order["mode"],
        status=status, rejection_reason=order["rejection_reason"],
        strategy=order["strategy_name"], broker_order_id=order["broker_order_id"],
    ))

    fills = await _query(
        "SELECT filled_qty, fill_price, commission, slippage, filled_at FROM fills "
        "WHERE order_id = :id ORDER BY filled_at", {"id": order_id},
    )
    filled = sum(_f(f["filled_qty"]) for f in fills)
    avg = sum(_f(f["filled_qty"]) * _f(f["fill_price"]) for f in fills) / filled if filled else None
    if fills:
        ref = order["limit_price"] or await _sizing_price(order)
        slip = sign * (avg - ref) / ref * 1e4 if ref and avg else None
        steps.append(_step(
            "fill", "done", fills[0]["filled_at"], "id",
            fills=fills, filled_qty=filled, avg_price=avg,
            commission=sum(_f(f["commission"]) for f in fills),
            ref_price=ref, ref_kind="limit" if order["limit_price"] else "sizing",
            slippage_bps=slip,
        ))
    elif status in ("REJECTED", "CANCELLED"):
        steps.append(_step("fill", "skipped", note=f"Order {status.lower()}, never filled"))
    else:
        steps.append(_step("fill", "unknown", note="No fill recorded yet"))

    if not fills:
        steps.append(_step("pnl", "skipped", note="Nothing filled"))
    else:
        pos = await _query(
            "SELECT current_price, quantity, updated_at FROM positions WHERE symbol = :s",
            {"s": order["symbol"]},
        )
        mark = _f(pos[0]["current_price"]) if pos else 0.0
        if mark > 0:
            pnl = sign * (mark - avg) * filled
            steps.append(_step(
                "pnl", "done", pos[0]["updated_at"], "id",
                mark=mark, pnl=pnl, pnl_pct=sign * (mark - avg) / avg * 100,
                basis="unrealised on this lot" if side == "BUY" else "vs holding",
                realised=None,
                note=("Realised P&L is not tracked per lot" if side == "BUY" else
                      "Positive = sold above today's mark. Realised P&L is not tracked per order"),
            ))
        else:
            steps.append(_step("pnl", "unknown", note="No current mark for this symbol"))

    return {"order_id": order_id, "symbol": order["symbol"], "side": side,
            "status": status, "steps": steps}
