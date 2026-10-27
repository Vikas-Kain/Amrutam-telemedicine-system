"""Database engine configuration, session lifecycle management, and connectivity probes."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Global singletons
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return or initialize the singleton AsyncEngine configured via Settings."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_pre_ping=True,
            echo=settings.debug,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return or initialize the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a dependency-injected database session with explicit transaction lifecycle.

    Yields an AsyncSession. If an active transaction is open and the execution completes
    normally, changes are committed automatically. If an unhandled exception occurs,
    the transaction is rolled back. In all cases, the session is cleanly closed on exit.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            if session.in_transaction():
                await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection(timeout_seconds: float = 3.0) -> bool:
    """Execute a lightweight probe query ('SELECT 1') to verify database readiness.

    Returns True if the database is reachable and responsive, False otherwise.
    Logs probe failures without exposing database URLs or credentials.
    """
    try:
        engine = get_engine()
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        # Never log database URL, username, or passwords in error messages
        logger.warning("Database connectivity probe failed: %s", type(exc).__name__)
        return False


async def close_database_connections() -> None:
    """Dispose of engine connection pool during graceful application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def reset_database_state() -> None:
    """Reset singletons for test isolation."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
