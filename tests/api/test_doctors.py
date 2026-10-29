import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.data import add_doctor
from tests.integration.helpers import count_rows
from tests.unit.auth_helpers import bearer, claims, roles


def as_role(*names: str) -> dict[str, str]:
    return bearer(claims(realm_access=roles(*names)))


async def test_no_token_is_401(client: AsyncClient) -> None:
    for path in ("/doctors", f"/doctors/{uuid.uuid4()}"):
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("who", [("patient",), ("doctor",), ("admin",)])
async def test_every_supported_role_can_read_the_directory(
    client: AsyncClient, fresh_db: AsyncEngine, who: tuple[str, ...]
) -> None:
    await add_doctor(fresh_db)
    response = await client.get("/doctors", headers=as_role(*who))
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("who", [("offline_access",), ("patient", "doctor")])
async def test_no_usable_role_or_two_roles_is_403(
    client: AsyncClient, who: tuple[str, ...]
) -> None:
    response = await client.get("/doctors", headers=as_role(*who))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_directory_exposes_only_id_name_and_specialty(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    await add_doctor(fresh_db, "Dr A", "Cardiology")
    item = (await client.get("/doctors", headers=bearer())).json()["items"][0]
    assert set(item) == {"id", "name", "specialty"}


async def test_only_active_doctors_are_listed_in_name_order(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    await add_doctor(fresh_db, "Dr B")
    await add_doctor(fresh_db, "Dr A")
    await add_doctor(fresh_db, "Dr Gone", active=False)
    await add_doctor(fresh_db, "Dr C")
    body = (await client.get("/doctors", headers=bearer())).json()
    assert [d["name"] for d in body["items"]] == ["Dr A", "Dr B", "Dr C"]
    assert body["total"] == 3


async def test_specialty_filter_is_case_insensitive(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    await add_doctor(fresh_db, "Dr Kid", "Paediatrics")
    await add_doctor(fresh_db, "Dr GP", "General Practice")
    body = (
        await client.get("/doctors", params={"specialty": "paediatrics"}, headers=bearer())
    ).json()
    assert [d["name"] for d in body["items"]] == ["Dr Kid"]
    assert body["total"] == 1


async def test_pagination(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    for name in ("Dr A", "Dr B", "Dr C"):
        await add_doctor(fresh_db, name)
    first = (await client.get("/doctors", params={"limit": 2}, headers=bearer())).json()
    assert [d["name"] for d in first["items"]] == ["Dr A", "Dr B"]
    assert first["total"] == 3
    second = (
        await client.get("/doctors", params={"limit": 2, "offset": 2}, headers=bearer())
    ).json()
    assert [d["name"] for d in second["items"]] == ["Dr C"]
    assert second["limit"] == 2
    assert second["offset"] == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_bad_paging_is_422(client: AsyncClient, params: dict[str, int]) -> None:
    response = await client.get("/doctors", params=params, headers=bearer())
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_one_doctor(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db, "Dr A", "Cardiology")
    response = await client.get(f"/doctors/{doctor_id}", headers=bearer())
    assert response.status_code == 200
    assert response.json() == {"id": str(doctor_id), "name": "Dr A", "specialty": "Cardiology"}


async def test_unknown_and_inactive_doctors_are_the_same_404(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    inactive = await add_doctor(fresh_db, active=False)
    for doctor_id in (uuid.uuid4(), inactive):
        response = await client.get(f"/doctors/{doctor_id}", headers=bearer())
        assert response.status_code == 404
        assert response.json()["code"] == "DOCTOR_NOT_FOUND"


async def test_malformed_doctor_id_is_422(client: AsyncClient) -> None:
    response = await client.get("/doctors/not-a-uuid", headers=bearer())
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_reading_the_directory_writes_nothing(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """A patient token reading the directory must not create a patient record."""
    await add_doctor(fresh_db)
    await client.get("/doctors", headers=bearer())
    assert await count_rows(fresh_db, "patients") == 0
