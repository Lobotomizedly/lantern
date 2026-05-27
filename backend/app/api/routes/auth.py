"""
Authentication routes for Lantern API.
Provides login, register, and token refresh endpoints.
"""

from datetime import timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DatabaseSession
from app.core.security import create_access_token, create_refresh_token
from app.models.orm import User

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    """Request model for user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """Request model for user login."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response model for authentication tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Response model for user data."""
    id: str
    email: str
    name: str
    role: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: DatabaseSession,
) -> TokenResponse:
    """
    Register a new user account.

    Creates a new user and returns access and refresh tokens.
    Uses database unique constraint to handle race conditions.
    """
    # Create new user
    user = User(
        id=uuid4(),
        email=request.email,
        name=request.name,
        hashed_password=_hash_password(request.password),
        role="analyst",
        is_active=True,
    )

    try:
        db.add(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Generate tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: DatabaseSession,
) -> TokenResponse:
    """
    Authenticate user and return tokens.
    """
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user or not _verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Generate tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


def _hash_password(password: str) -> str:
    """
    Hash password using bcrypt with automatic salt generation.

    Bcrypt includes the salt in the output hash, making it resistant to
    rainbow table attacks and providing adaptive cost factor for future-proofing.
    """
    return pwd_context.hash(password)


def _verify_password(password: str, hashed: str) -> bool:
    """
    Verify password against hash.

    Supports backwards compatibility with legacy SHA256 hashes:
    - SHA256 hashes are 64 character hex strings
    - Bcrypt hashes start with '$2b$' and are longer

    If a legacy SHA256 hash is detected, verification will still work,
    but users should be prompted to update their password on next login
    to migrate to bcrypt.
    """
    import hashlib

    # Check if this is a legacy SHA256 hash (64 char hex string, no bcrypt prefix)
    if len(hashed) == 64 and not hashed.startswith('$'):
        # Legacy SHA256 verification for backwards compatibility
        # TODO: Log warning and prompt user to update password after successful login
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        return legacy_hash == hashed

    # Bcrypt verification
    return pwd_context.verify(password, hashed)
