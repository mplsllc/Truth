"""Shared test fixtures for the Truth test suite."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import event, types
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.models import Article, Feed, StoryCluster  # noqa: F401 -- register models


# Use SQLite async for fast unit tests (no PostgreSQL required)
TEST_DB_PATH = Path(__file__).parent / "test.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """Create a test database engine."""
    # Remove stale test db
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    # SQLite needs special handling for foreign keys
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Swap Vector columns to Text for SQLite compatibility
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, Vector):
                column.type = types.Text()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

    # Cleanup test db file
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session for each test.

    Uses a connection-level transaction that wraps the entire test,
    then rolls back after the test completes. This ensures that even
    session.commit() calls inside tested code are undone, providing
    proper test isolation.
    """
    async with test_engine.connect() as connection:
        # Start a transaction that wraps the entire test
        transaction = await connection.begin()

        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        yield session

        await session.close()
        # Rollback the outer transaction, undoing everything including commits
        await transaction.rollback()


@pytest.fixture
def mock_settings() -> dict[str, Any]:
    """Provide overridable test settings."""
    return {
        "database_url": TEST_DATABASE_URL,
        "redis_url": "redis://localhost:6379/0",
        "ollama_url": "http://localhost:11434",
        "admin_username": "admin",
        "admin_password": "testpassword",
        "polling_interval_minutes": 1,
        "dedup_similarity_threshold": 0.83,
        "log_level": "DEBUG",
    }


@pytest.fixture
async def async_client():
    """Provide an async HTTP client for testing FastAPI endpoints."""
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
