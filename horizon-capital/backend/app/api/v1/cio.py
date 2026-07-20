"""CIO (Chief Investment Officer) control endpoints: mode, override, halt, status."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import SystemMode, settings
from app.core.redis_client import redis_client
from app.dependencies import get_current_user

router = APIRouter(prefix="/cio", tags=["cio"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SetModeRequest(BaseModel):
    mode: SystemMode = Field(..., description="Target system mode")


class OverrideRequest(BaseModel):
    action: str = Field(..., description="APPROVE or REJECT")
    order_id: str | None = Field(None, description="Specific order ID to override")
    reason: str | None = Field(None, description="Reason for override")


class HaltRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    duration_minutes: int | None = Field(
        None, ge=1, le=1440, description="Auto-resume after N minutes"
    )


class CIOStatusResponse(BaseModel):
    system_mode: str
    kill_switch_active: bool
    halt_active: bool
    halt_reason: str | None = None
    halt_until: str | None = None
    timestamp: datetime


class ModeResponse(BaseModel):
    previous_mode: str
    new_mode: str
    message: str


class OverrideResponse(BaseModel):
    action: str
    order_id: str | None = None
    message: str


class HaltResponse(BaseModel):
    halt_active: bool
    reason: str
    duration_minutes: int | None = None
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=CIOStatusResponse)
async def get_cio_status(
    _user: dict = Depends(get_current_user),
) -> CIOStatusResponse:
    """Get the current CIO / system status from Redis."""
    mode = await redis_client.get("horizon:system:mode") or settings.system_mode.value
    halted = await redis_client.get("horizon:system:halted")
    halt_reason = await redis_client.get("horizon:system:halt_reason")
    halt_until = await redis_client.get("horizon:system:halt_until")

    return CIOStatusResponse(
        system_mode=mode,
        kill_switch_active=(halted == "1"),
        halt_active=(halted == "1"),
        halt_reason=halt_reason,
        halt_until=halt_until,
        timestamp=datetime.now(UTC),
    )


@router.post("/mode", response_model=ModeResponse)
async def set_mode(
    body: SetModeRequest,
    _user: dict = Depends(get_current_user),
) -> ModeResponse:
    """Change the system operating mode (PAPER_TRADING, HUMAN_APPROVAL, FULLY_AUTONOMOUS)."""
    previous = await redis_client.get("horizon:system:mode") or settings.system_mode.value
    new_mode = body.mode.value

    await redis_client.set("horizon:system:mode", new_mode)

    # Broadcast mode change
    import orjson

    await redis_client.publish(
        "horizon.system.mode_change",
        orjson.dumps({"previous": previous, "new": new_mode}).decode(),
    )

    return ModeResponse(
        previous_mode=previous,
        new_mode=new_mode,
        message=f"System mode changed from {previous} to {new_mode}",
    )


@router.post("/override", response_model=OverrideResponse)
async def cio_override(
    body: OverrideRequest,
    _user: dict = Depends(get_current_user),
) -> OverrideResponse:
    """CIO manual override: approve or reject a pending decision/order."""
    if body.action not in ("APPROVE", "REJECT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be APPROVE or REJECT",
        )

    import orjson

    payload = {
        "action": body.action,
        "order_id": body.order_id,
        "reason": body.reason,
    }
    await redis_client.publish(
        "horizon.cio.override",
        orjson.dumps(payload).decode(),
    )

    return OverrideResponse(
        action=body.action,
        order_id=body.order_id,
        message=f"Override {body.action} issued"
        + (f" for order {body.order_id}" if body.order_id else ""),
    )


@router.post("/halt", response_model=HaltResponse)
async def halt_system(
    body: HaltRequest,
    _user: dict = Depends(get_current_user),
) -> HaltResponse:
    """Halt all system operations with a reason. Optionally auto-resume after N minutes."""
    await redis_client.set("horizon:system:halted", "1")
    await redis_client.set("horizon:system:halt_reason", body.reason)

    if body.duration_minutes:
        from datetime import timedelta

        resume_at = datetime.now(UTC) + timedelta(minutes=body.duration_minutes)
        await redis_client.set("horizon:system:halt_until", resume_at.isoformat())
        # Set a TTL-based auto-clear
        await redis_client.setex(
            "horizon:system:halt_timer",
            body.duration_minutes * 60,
            "active",
        )
    else:
        await redis_client.delete("horizon:system:halt_until")

    import orjson

    await redis_client.publish(
        "horizon.system.halt",
        orjson.dumps({"reason": body.reason, "duration_minutes": body.duration_minutes}).decode(),
    )

    return HaltResponse(
        halt_active=True,
        reason=body.reason,
        duration_minutes=body.duration_minutes,
        message=f"System halted: {body.reason}"
        + (f" (auto-resume in {body.duration_minutes}m)" if body.duration_minutes else ""),
    )
