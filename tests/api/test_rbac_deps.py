"""The route-level guards, exercised through throwaway routes. No database needed."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

import pytest
import pytest_asyncio
from app.auth.jwks import JwksCache
from app.auth.tokens import Principal, TokenConfig, TokenValidator
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.auth.deps import get_token_validator, require_permission, require_roles
from app.main import create_app
from tests.unit.auth_helpers import AUDIENCE, ISSUER, KEY_A, FakeJwks, bearer, claims, roles

WHO = {
    "patient": ["patient"],
    "doctor": ["doctor"],
    "admin_plain": ["admin"],
    "admin_view": ["admin", "view_any"],
    "admin_full": ["admin", "book_for_patient", "manage_any", "view_any"],
    "no_role": ["offline_access"],
    "two_roles": ["patient", "doctor"],
    "patient_with_permission_roles": ["patient", "manage_any", "view_any"],
}

ALLOWED = {
    "/_t/doctor-only": {"doctor"},
    "/_t/staff": {"doctor", "admin_plain", "admin_view", "admin_full"},
    "/_t/manage": {"admin_full"},
    "/_t/view": {"admin_view", "admin_full"},
}


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    validator = TokenValidator(TokenConfig(ISSUER, AUDIENCE), JwksCache(FakeJwks(KEY_A)))
    app = create_app()
    app.dependency_overrides[get_token_validator] = lambda: validator

    @app.get("/_t/doctor-only")
    async def doctor_only(
        p: Annotated[Principal, Depends(require_roles("doctor"))],
    ) -> dict[str, str]:
        return {"sub": p.sub}

    @app.get("/_t/staff")
    async def staff(
        p: Annotated[Principal, Depends(require_roles("doctor", "admin"))],
    ) -> dict[str, str]:
        return {"sub": p.sub}

    @app.get("/_t/manage")
    async def manage(
        p: Annotated[Principal, Depends(require_permission("manage_any"))],
    ) -> dict[str, str]:
        return {"sub": p.sub}

    @app.get("/_t/view")
    async def view(
        p: Annotated[Principal, Depends(require_permission("view_any"))],
    ) -> dict[str, str]:
        return {"sub": p.sub}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.mark.parametrize("path", list(ALLOWED))
@pytest.mark.parametrize("who", list(WHO))
async def test_role_and_permission_matrix(client: AsyncClient, path: str, who: str) -> None:
    response = await client.get(path, headers=bearer(claims(realm_access=roles(*WHO[who]))))
    if who in ALLOWED[path]:
        assert response.status_code == 200
    else:
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", list(ALLOWED))
async def test_no_token_is_401_before_any_role_check(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401


async def test_denial_is_audited_without_personal_data(client: AsyncClient, caplog: Any) -> None:
    headers = bearer(
        claims(
            sub="actor-1",
            name="Pat One",
            email="pat@example.test",
            realm_access=roles("admin", "view_any"),
        )
    )
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        response = await client.get("/_t/manage", headers=headers)
    assert response.status_code == 403
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    assert len(entries) == 1
    assert entries[0]["action"] == "authorize"
    assert entries[0]["outcome"] == "denied"
    assert entries[0]["actor"] == "actor-1"
    assert entries[0]["role"] == "admin"
    assert entries[0]["reason"] == "permission_required:manage_any"
    assert "Pat" not in caplog.text
    assert "example.test" not in caplog.text
