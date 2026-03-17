"""
Database setup — SQLite by default, PostgreSQL-ready.

SQLAlchemy 2.0 async session factory.
SQLite is the default because it requires zero setup — just run the app.
Switching to PostgreSQL is a single env var change: DATABASE_URL=postgresql+asyncpg://...
"""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .orm_models import Base


def _make_async_url(url: str) -> str:
    """Convert sync SQLAlchemy URLs to async variants."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine(database_url: str) -> AsyncEngine:
    async_url = _make_async_url(database_url)
    connect_args = {"check_same_thread": False} if "sqlite" in async_url else {}
    return create_async_engine(
        async_url,
        connect_args=connect_args,
        echo=False,
        pool_pre_ping=True,
    )


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(database_url: str) -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    engine = get_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session(database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager / dependency for FastAPI."""
    engine = get_engine(database_url)
    factory = get_session_factory(engine)
    async with factory() as session:
        yield session
