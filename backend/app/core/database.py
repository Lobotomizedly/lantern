"""
Database pool wrapper for Lantern backend.

This module provides a DatabasePool class that wraps the SQLAlchemy
async session factory for centralized connection management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import (
    async_session_factory,
    engine,
    init_database,
    close_database,
)


class DatabasePool:
    """
    Database pool wrapper for managing async database connections.

    Provides methods for connecting, disconnecting, and obtaining
    database sessions in a centralized manner.

    Example:
        async def main():
            await database_pool.connect()
            try:
                async with database_pool.session() as session:
                    result = await session.execute(select(User))
                    users = result.scalars().all()
            finally:
                await database_pool.disconnect()
    """

    def __init__(self) -> None:
        """Initialize the database pool wrapper."""
        self._connected: bool = False

    async def connect(self) -> None:
        """
        Initialize database connections and extensions.

        This should be called on application startup to set up
        the database with required extensions (pgvector, uuid-ossp)
        and create tables if they don't exist.
        """
        await init_database()
        self._connected = True

    async def disconnect(self) -> None:
        """
        Close all database connections.

        This should be called on application shutdown to properly
        dispose of the connection pool and release resources.
        """
        await close_database()
        self._connected = False

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session as an async context manager.

        Yields:
            AsyncSession: Database session that auto-commits on success
                and rolls back on exception.

        Raises:
            RuntimeError: If the database pool is not connected.

        Example:
            async with database_pool.session() as session:
                user = User(name="John")
                session.add(user)
                # Commits automatically on context exit
        """
        if not self._connected:
            raise RuntimeError(
                "Database pool is not connected. Call connect() first."
            )

        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @property
    def is_connected(self) -> bool:
        """Check if the database pool is connected."""
        return self._connected

    @property
    def engine(self):
        """Get the underlying SQLAlchemy async engine."""
        return engine


# Global database pool instance
database_pool = DatabasePool()
