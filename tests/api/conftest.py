from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.deps import get_token_validator
from app.auth.jwks import JwksCache
from app.auth.tokens import TokenConfig, TokenValidator
from app.db.engine import create_session_factory, get_session_factory
from app.main import create_app
from tests.unit.auth_helpers import AUDIENCE, ISSUER, KEY_A, FakeJwks


@pytest.fixture
def jwks() -> FakeJwks:
    return FakeJwks(KEY_A)


@pytest_asyncio.fixture
async def client(fresh_db: AsyncEngine, jwks: FakeJwks) -> AsyncIterator[AsyncClient]:
    """The real app, with a fake identity provider and the real (emptied) Postgres."""
    validator = TokenValidator(TokenConfig(ISSUER, AUDIENCE), JwksCache(jwks))
    factory = create_session_factory(fresh_db)
    app = create_app()
    app.dependency_overrides[get_token_validator] = lambda: validator
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
