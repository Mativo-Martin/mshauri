import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.integration.db import db_url, recreate_database, run_alembic

TEST_DB = "mshauri_test"
COMMIT_DB = "mshauri_commit_test"


@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    """A fresh database migrated to head, built once per test session."""
    asyncio.run(recreate_database(TEST_DB))
    url = db_url(TEST_DB)
    run_alembic(url, "upgrade", "head")
    return url


@pytest_asyncio.fixture
async def conn(migrated_db_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back."""
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture(scope="session")
def commit_db_url() -> str:
    """A separate migrated database for tests that really commit."""
    asyncio.run(recreate_database(COMMIT_DB))
    url = db_url(COMMIT_DB)
    run_alembic(url, "upgrade", "head")
    return url


@pytest_asyncio.fixture
async def fresh_db(commit_db_url: str) -> AsyncIterator[AsyncEngine]:
    """The commit database, emptied before each test."""
    engine = create_async_engine(commit_db_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE appointments, schedule_exceptions, doctor_schedules, "
                "patients, doctors CASCADE"
            )
        )
    yield engine
    await engine.dispose()
