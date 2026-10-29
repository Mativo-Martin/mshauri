import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.deps import get_token_validator
from app.auth.jwks import JwksCache
from app.auth.tokens import TokenConfig, TokenValidator
from app.core.clock import utc_now
from app.db.engine import create_session_factory, get_engine, get_session_factory
from app.main import create_app
from tests.integration.db import db_url, recreate_database, run_alembic
from tests.unit.auth_helpers import AUDIENCE, ISSUER, KEY_A, FakeJwks

# The pinned "now" for API tests: Tuesday 2030-01-01 00:00 UTC (03:00 in Nairobi).
NOW = datetime(2030, 1, 1, tzinfo=UTC)

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


@pytest.fixture
def jwks() -> FakeJwks:
    return FakeJwks(KEY_A)


@pytest_asyncio.fixture
async def app(fresh_db: AsyncEngine, jwks: FakeJwks) -> FastAPI:
    """The real app, a fake identity provider, the real (emptied) Postgres and a pinned clock.

    Tests may change `app.dependency_overrides[utc_now]` to move the clock.
    """
    validator = TokenValidator(TokenConfig(ISSUER, AUDIENCE), JwksCache(jwks))
    factory = create_session_factory(fresh_db)
    application = create_app()
    application.dependency_overrides[get_token_validator] = lambda: validator
    application.dependency_overrides[get_engine] = lambda: fresh_db
    application.dependency_overrides[get_session_factory] = lambda: factory
    application.dependency_overrides[utc_now] = lambda: NOW
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
