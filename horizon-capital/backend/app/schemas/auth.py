"""Authentication and authorization schemas."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Schema for user login."""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    """Schema for JWT token pair returned after authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token TTL in seconds")


class RefreshRequest(BaseModel):
    """Schema for refreshing an expired access token."""

    refresh_token: str
