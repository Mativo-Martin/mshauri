import asyncio
import json
import logging
import time
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Doctor
from tests.integration.helpers import count_rows
from tests.unit.auth_helpers import FakeJwks, bearer, claims, roles

ME_FIELDS = {"sub", "role", "permissions", "patient_id", "doctor_id", "name", "email", "phone"}


async def get_me(client: AsyncClient, *, drop: tuple[str, ...] = (), **overrides: Any) -> Response:
    return await client.get("/me", headers=bearer(claims(drop=drop, **overrides)))


# --- authentication: 401 ----------------------------------------------------


async def test_no_token_is_401_with_the_standard_shape(client: AsyncClient) -> None:
    response = await client.get("/me")
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "UNAUTHENTICATED"


async def test_wrong_scheme_is_401(client: AsyncClient) -> None:
    response = await client.get("/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_expired_token_is_401(client: AsyncClient) -> None:
    response = await get_me(client, exp=int(time.time()) - 3600)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_error_body_never_contains_the_token(client: AsyncClient) -> None:
    headers = bearer(claims(exp=int(time.time()) - 3600))
    response = await client.get("/me", headers=headers)
    assert headers["Authorization"].split()[1] not in response.text


async def test_identity_provider_down_is_503_not_401(client: AsyncClient, jwks: FakeJwks) -> None:
    jwks.fail = True  # nothing cached yet
    response = await get_me(client)
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_UNAVAILABLE"


# --- patients: provisioned on first call ------------------------------------


async def test_patient_is_provisioned_on_first_call(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    response = await get_me(client, sub="kc-patient-1")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == ME_FIELDS
    assert body["role"] == "patient"
    assert body["sub"] == "kc-patient-1"
    assert body["patient_id"] is not None
    assert body["doctor_id"] is None
    assert body["permissions"] == []
    assert body["name"] == "Pat One"
    assert body["email"] == "pat@example.test"
    assert body["phone"] is None
    assert await count_rows(fresh_db, "patients") == 1


async def test_second_call_returns_the_same_patient(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    first = (await get_me(client, sub="kc-patient-1")).json()
    second = (await get_me(client, sub="kc-patient-1")).json()
    assert first["patient_id"] == second["patient_id"]
    assert await count_rows(fresh_db, "patients") == 1


async def test_concurrent_first_calls_create_exactly_one_patient(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    headers = bearer(claims(sub="kc-concurrent"))
    responses = await asyncio.gather(*(client.get("/me", headers=headers) for _ in range(10)))
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["patient_id"] for response in responses}) == 1
    assert await count_rows(fresh_db, "patients") == 1


async def test_different_subjects_are_different_patients(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    one = (await get_me(client, sub="kc-a")).json()
    two = (await get_me(client, sub="kc-b")).json()
    assert one["patient_id"] != two["patient_id"]
    assert await count_rows(fresh_db, "patients") == 2


async def test_name_falls_back_to_email_then_to_a_placeholder(client: AsyncClient) -> None:
    by_email = await get_me(client, sub="kc-x", drop=("name",))
    assert by_email.json()["name"] == "pat@example.test"
    bare = await get_me(client, sub="kc-y", drop=("name", "email"))
    assert bare.json()["name"] == "Unnamed patient"
    assert bare.json()["email"] is None


async def test_provisioning_is_audited_without_personal_data(
    client: AsyncClient, caplog: Any
) -> None:
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        response = await get_me(client, sub="kc-audited")
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "profile.provision"
    assert entry["outcome"] == "success"
    assert entry["actor"] == "kc-audited"
    assert entry["resource_type"] == "patient"
    assert entry["resource_id"] == response.json()["patient_id"]
    raw = caplog.text
    assert "Pat One" not in raw
    assert "example.test" not in raw


# --- doctors: linked, never created -----------------------------------------


async def test_unlinked_doctor_is_403_and_creates_nothing(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    response = await get_me(client, sub="kc-doc-x", realm_access=roles("doctor"))
    assert response.status_code == 403
    assert response.json()["code"] == "PROFILE_NOT_PROVISIONED"
    assert await count_rows(fresh_db, "patients") == 0
    assert await count_rows(fresh_db, "doctors") == 0


async def test_linked_doctor_sees_their_doctor_id(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    async with fresh_db.begin() as conn:
        await conn.execute(insert(Doctor).values(name="Dr Linked", keycloak_sub="kc-doc-1"))
    response = await get_me(client, sub="kc-doc-1", realm_access=roles("doctor"))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "doctor"
    assert body["doctor_id"] is not None
    assert body["patient_id"] is None
    assert body["name"] == "Dr Linked"
    assert body["email"] is None
    assert await count_rows(fresh_db, "patients") == 0


# --- admins: no profile -----------------------------------------------------


async def test_admin_gets_200_with_permissions_and_no_profile(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    response = await get_me(
        client,
        sub="kc-admin",
        realm_access=roles("admin", "view_any", "manage_any", "offline_access"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["permissions"] == ["manage_any", "view_any"]
    assert body["patient_id"] is None
    assert body["doctor_id"] is None
    assert await count_rows(fresh_db, "patients") == 0


async def test_admin_without_permissions_has_an_empty_list(client: AsyncClient) -> None:
    response = await get_me(client, realm_access=roles("admin"))
    assert response.json()["permissions"] == []


async def test_permission_roles_do_nothing_without_the_admin_role(client: AsyncClient) -> None:
    response = await get_me(client, realm_access=roles("patient", "manage_any"))
    assert response.status_code == 200
    assert response.json()["permissions"] == []


# --- no usable role: 403 and nothing written --------------------------------


async def test_token_with_no_supported_role_is_403(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    response = await get_me(client, realm_access=roles("offline_access", "uma_authorization"))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert await count_rows(fresh_db, "patients") == 0


async def test_token_with_two_base_roles_is_403(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    response = await get_me(client, realm_access=roles("patient", "doctor"))
    assert response.status_code == 403
    assert await count_rows(fresh_db, "patients") == 0
