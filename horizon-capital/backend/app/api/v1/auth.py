"""Authentication endpoints: login and token refresh."""

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.core.resilience import RateLimiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# Rate limit: 5 login attempts per 60 seconds
_login_limiter = RateLimiter(name="auth_login", max_calls=5, window_seconds=60.0)

# Pre-hash the default password at module load so verify_password works
_hashed_default_password: str | None = None


def _get_hashed_default_password() -> str:
    global _hashed_default_password
    if _hashed_default_password is None:
        _hashed_default_password = hash_password(settings.cio_default_password)
    return _hashed_default_password


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """Authenticate the CIO user and return a JWT token pair."""
    if not await _login_limiter.acquire():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in 60 seconds.",
        )

    if body.username != settings.cio_default_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(body.password, _get_hashed_default_password()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token_data = {"sub": body.username, "role": "cio"}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    """Issue a new access token using a valid refresh token."""
    payload = decode_token(body.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not a refresh token",
        )

    token_data = {"sub": payload["sub"], "role": payload.get("role", "cio")}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )
