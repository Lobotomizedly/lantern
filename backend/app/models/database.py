"""
SQLAlchemy async database setup with pgvector extension.

This module provides the async database engine, session factory,
and connection utilities for the Lantern platform.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    All models should inherit from this base class to be included
    in migrations and have access to common functionality.
    """

    pass


def create_engine() -> AsyncEngine:
    """
    Create and configure the async SQLAlchemy engine.

    Returns:
        AsyncEngine: Configured async database engine.
    """
    engine = create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        echo=settings.database_echo,
        pool_pre_ping=True,  # Enable connection health checks
    )
    return engine


# Global async engine instance
engine = create_engine()

# Async session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI to get database sessions.

    Yields:
        AsyncSession: Database session for the request.

    Example:
        @app.get("/items")
        async def get_items(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(Item))
            return result.scalars().all()
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions outside of FastAPI dependencies.

    Yields:
        AsyncSession: Database session.

    Example:
        async with get_session_context() as session:
            result = await session.execute(select(Item))
            items = result.scalars().all()
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_database() -> None:
    """
    Initialize the database with required extensions and tables.

    This function should be called on application startup to ensure
    the database is properly configured with the pgvector extension.
    """
    from app.core.config import settings

    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Enable UUID extension for uuid_generate_v4()
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

        # Only auto-create tables in development
        # Production should use Alembic migrations
        if settings.is_development:
            from app.models.orm import Base as ORMBase
            await conn.run_sync(lambda sync_conn: ORMBase.metadata.create_all(sync_conn, checkfirst=True))

        # Apply schema migrations (add missing columns)
        # This is a simple migration approach for Railway deployments
        try:
            await conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255);
            """))
        except Exception:
            pass  # Column may already exist or table may not exist yet


async def close_database() -> None:
    """
    Close database connections.

    This function should be called on application shutdown to properly
    dispose of the connection pool.
    """
    await engine.dispose()


async def health_check() -> bool:
    """
    Check database connectivity.

    Returns:
        bool: True if database is healthy, False otherwise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
