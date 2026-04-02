"""JWT authentication, password hashing, and validation."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# Password policy
MIN_PASSWORD_LENGTH = 8
PASSWORD_RULES = [
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[a-z]", "at least one lowercase letter"),
    (r"[0-9]", "at least one digit"),
]


class PasswordValidationError(ValueError):
    """Raised when a password does not meet the policy."""


def validate_password(password: str) -> None:
    """Validate password against policy. Raises PasswordValidationError on failure."""
    errors: list[str] = []
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    for pattern, description in PASSWORD_RULES:
        if not re.search(pattern, password):
            errors.append(description)
    if errors:
        raise PasswordValidationError(
            f"Password does not meet policy: {'; '.join(errors)}"
        )


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None
