"""
JWT security module for Lantern backend.

This module provides JWT token creation and validation utilities
for authentication and authorization.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class TokenPayload(BaseModel):
    """
    JWT token payload model.

    Contains the standard JWT claims and custom claims
    for user identification and authorization.
    """

    sub: UUID = Field(..., description="Subject (user ID)")
    exp: datetime = Field(..., description="Expiration time")
    iat: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Issued at time",
    )
    jti: Optional[str] = Field(default=None, description="JWT ID (unique identifier)")
    type: str = Field(default="access", description="Token type (access or refresh)")

    @field_validator("exp", mode="before")
    @classmethod
    def validate_exp(cls, v: Any) -> datetime:
        """Convert timestamp to datetime if necessary."""
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v, tz=timezone.utc)
        return v

    @field_validator("iat", mode="before")
    @classmethod
    def validate_iat(cls, v: Any) -> datetime:
        """Convert timestamp to datetime if necessary."""
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v, tz=timezone.utc)
        if v is None:
            return datetime.now(timezone.utc)
        return v

    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        return datetime.now(timezone.utc) > self.exp


class TokenError(Exception):
    """Exception raised for token validation errors."""

    def __init__(self, message: str = "Invalid token"):
        self.message = message
        super().__init__(self.message)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a new JWT access token.

    Args:
        data: Dictionary containing token payload data. Must include 'sub' key
            with the user ID (UUID or string).
        expires_delta: Optional custom expiration time. If not provided,
            uses the configured jwt_access_token_expire_minutes.

    Returns:
        str: Encoded JWT token string.

    Example:
        token = create_access_token({"sub": str(user.id)})
        # or with custom expiration
        token = create_access_token(
            {"sub": str(user.id)},
            expires_delta=timedelta(hours=1)
        )
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a new JWT refresh token.

    Args:
        data: Dictionary containing token payload data. Must include 'sub' key
            with the user ID (UUID or string).
        expires_delta: Optional custom expiration time. If not provided,
            uses the configured jwt_refresh_token_expire_days.

    Returns:
        str: Encoded JWT refresh token string.

    Example:
        token = create_refresh_token({"sub": str(user.id)})
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def decode_access_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT access token.

    Args:
        token: The JWT token string to decode.

    Returns:
        TokenPayload: Validated token payload.

    Raises:
        TokenError: If the token is invalid, expired, or malformed.

    Example:
        try:
            payload = decode_access_token(token)
            user_id = payload.sub
        except TokenError as e:
            print(f"Token validation failed: {e.message}")
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )

        # Validate required fields
        if "sub" not in payload:
            raise TokenError("Token missing 'sub' claim")

        # Convert sub to UUID
        try:
            payload["sub"] = UUID(payload["sub"])
        except (ValueError, TypeError) as e:
            raise TokenError(f"Invalid 'sub' claim: {e}")

        token_payload = TokenPayload(**payload)

        # Check expiration
        if token_payload.is_expired:
            raise TokenError("Token has expired")

        return token_payload

    except JWTError as e:
        raise TokenError(f"Token decode error: {str(e)}")


def verify_token(token: str, token_type: str = "access") -> TokenPayload:
    """
    Verify a token and check its type.

    Args:
        token: The JWT token string to verify.
        token_type: Expected token type ("access" or "refresh").

    Returns:
        TokenPayload: Validated token payload.

    Raises:
        TokenError: If the token is invalid or has wrong type.
    """
    payload = decode_access_token(token)

    if payload.type != token_type:
        raise TokenError(f"Invalid token type. Expected {token_type}, got {payload.type}")

    return payload
