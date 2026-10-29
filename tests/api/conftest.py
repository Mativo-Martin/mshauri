from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.deps import get_token_validator
from app.auth.jwks import JwksCache
from app.auth.tokens import TokenConfig, TokenValidator
from app.core.clock import utc_now
from app.db.engine import create_session_factory, get_session_factory
from app.main import create_app
from tests.unit.auth_helpers import AUDIENCE, ISSUER, KEY_A, FakeJwks

# The pinned "now" for API tests: Tuesday 2030-01-01 00:00 UTC (03:00 in Nairobi).
NOW = datetime(2030, 1, 1, tzinfo=UTC)


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
    application.dependency_overrides[get_session_factory] = lambda: factory
    application.dependency_overrides[utc_now] = lambda: NOW
    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
