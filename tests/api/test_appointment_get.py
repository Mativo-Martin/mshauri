import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.data import add_doctor, link_doctor
from tests.api.helpers import (
    SLOT,
    admin,
    cancel,
    doctor,
    get_appointment,
    make_booking,
    patient,
)
from tests.unit.auth_helpers import bearer, claims, roles


async def setup(client: AsyncClient, engine: AsyncEngine) -> tuple[uuid.UUID, str]:
    doctor_id = await add_doctor(engine, "Dr A")
    return doctor_id, await make_booking(client, doctor_id)


# --- access order ---------------------------------------------------------------


async def test_no_token_is_401(client: AsyncClient) -> None:
    response = await client.get(f"/appointments/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_a_token_with_no_usable_role_is_403(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    headers = bearer(claims(realm_access=roles("offline_access")))
    assert (await get_appointment(client, headers, appointment_id)).status_code == 403


async def test_a_malformed_id_is_422(client: AsyncClient) -> None:
    response = await get_appointment(client, patient(), "not-a-uuid")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_an_unknown_id_is_404(client: AsyncClient) -> None:
    response = await get_appointment(client, patient(), str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"


# --- patient -------------------------------------------------------------------------


async def test_a_patient_reads_their_own_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    response = await get_appointment(client, patient(), appointment_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == appointment_id
    assert body["status"] == "booked"
    assert body["start_at"] == SLOT
    assert body["doctor"] == {"id": str(doctor_id), "name": "Dr A"}
    assert "cancel_reason" not in body
    assert "cancelled_at" not in body
    assert "email" not in response.text
    assert "phone" not in response.text


async def test_a_cancelled_appointment_shows_its_reason(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    await cancel(client, patient(), appointment_id, "Feeling better")
    body = (await get_appointment(client, patient(), appointment_id)).json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Feeling better"
    assert body["cancelled_at"] is not None


async def test_another_patient_is_forbidden(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await get_appointment(client, patient("kc-p2"), appointment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


# --- doctor --------------------------------------------------------------------------


async def test_a_doctor_reads_an_appointment_on_their_own_schedule(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    await link_doctor(fresh_db, doctor_id, "kc-doc1")
    response = await get_appointment(client, doctor(), appointment_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["patient"]) == {"id", "name"}  # name only, no contact details
    assert "email" not in response.text
    assert "phone" not in response.text


async def test_a_doctor_cannot_read_another_doctors_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    other = await add_doctor(fresh_db, "Dr B")
    await link_doctor(fresh_db, other, "kc-doc2")
    response = await get_appointment(client, doctor("kc-doc2"), appointment_id)
    assert response.status_code == 403


async def test_an_unlinked_doctor_is_403_profile_not_provisioned(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await get_appointment(client, doctor("kc-nobody"), appointment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "PROFILE_NOT_PROVISIONED"


# --- admin ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("permissions", "status"),
    [
        ((), 403),
        (("manage_any",), 403),
        (("book_for_patient",), 403),
        (("view_any",), 200),
    ],
)
async def test_an_admin_needs_view_any(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...], status: int
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await get_appointment(client, admin(*permissions), appointment_id)
    assert response.status_code == status, response.text


async def test_a_refused_admin_learns_nothing_about_ids(client: AsyncClient) -> None:
    response = await get_appointment(client, admin("manage_any"), str(uuid.uuid4()))
    assert response.status_code == 403  # not 404


async def test_an_admin_with_view_any_gets_404_for_an_unknown_id(client: AsyncClient) -> None:
    response = await get_appointment(client, admin("view_any"), str(uuid.uuid4()))
    assert response.status_code == 404
