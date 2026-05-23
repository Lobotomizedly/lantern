"""
Dependency injection for Lantern API.
Provides database sessions, authentication, and common dependencies.
"""

from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_pool
from app.core.security import decode_access_token, TokenPayload
from app.models.orm import User
from app.models.schemas.common import PaginationParams


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.
    Automatically handles session lifecycle and rollback on errors.
    """
    async with database_pool.session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> TokenPayload:
    """
    Dependency that extracts and validates the JWT token from Authorization header.
    Returns the decoded token payload.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


CurrentUserToken = Annotated[TokenPayload, Depends(get_current_user_token)]


async def get_current_user(
    db: DatabaseSession,
    token: CurrentUserToken,
) -> User:
    """
    Dependency that retrieves the current authenticated user from the database.
    """
    user = await db.get(User, token.sub)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_active_user(
    current_user: CurrentUser,
) -> User:
    """
    Dependency that ensures the current user is active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


ActiveUser = Annotated[User, Depends(get_current_active_user)]


def require_role(required_roles: list[str]):
    """
    Factory function that creates a dependency requiring specific roles.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: Annotated[User, Depends(require_role(["admin"]))]):
            ...
    """
    async def role_checker(current_user: CurrentUser) -> User:
        if current_user.role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {', '.join(required_roles)}",
            )
        return current_user

    return role_checker


AdminUser = Annotated[User, Depends(require_role(["admin"]))]
AnalystUser = Annotated[User, Depends(require_role(["admin", "analyst"]))]


def get_pagination_params(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> PaginationParams:
    """
    Dependency that extracts and validates pagination parameters.
    """
    return PaginationParams(page=page, page_size=page_size)


Pagination = Annotated[PaginationParams, Depends(get_pagination_params)]


async def get_optional_user(
    db: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User | None:
    """
    Dependency that optionally retrieves the current user.
    Returns None if no valid authentication is provided.
    """
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    try:
        payload = decode_access_token(token)
        user = await db.get(User, payload.sub)
        return user if user and user.is_active else None
    except Exception:
        return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def validate_uuid(value: str, field_name: str = "id") -> UUID:
    """
    Utility function to validate UUID strings.
    """
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID format for {field_name}: {value}",
        )


class SubjectAccess:
    """
    Dependency class to verify user has access to a specific subject.
    """

    def __init__(self, require_owner: bool = False):
        self.require_owner = require_owner

    async def __call__(
        self,
        subject_id: UUID,
        db: DatabaseSession,
        current_user: CurrentUser,
    ) -> UUID:
        from app.models.orm import Subject

        subject = await db.get(Subject, subject_id)

        if not subject:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject with id '{subject_id}' not found",
            )

        if subject.is_archived:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Subject with id '{subject_id}' has been archived",
            )

        # Check access based on organization or ownership
        if self.require_owner and subject.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have owner access to this subject",
            )

        if (
            subject.organization_id
            and current_user.organization_id != subject.organization_id
            and current_user.role != "admin"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this subject",
            )

        return subject_id


VerifiedSubjectAccess = Annotated[UUID, Depends(SubjectAccess())]
OwnerSubjectAccess = Annotated[UUID, Depends(SubjectAccess(require_owner=True))]
