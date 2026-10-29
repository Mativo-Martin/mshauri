import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.data import add_doctor
from tests.api.helpers import (
    SLOT,
    admin,
    cancel,
    doctor,
    make_booking,
    patient,
    patient_appointments,
    patient_id_of,
)
from tests.unit.auth_helpers import bearer, claims, roles

S0900 = SLOT
S0930 = "2030-01-07T09:30:00+03:00"
S1000 = "2030-01-07T10:00:00+03:00"


async def setup(client: AsyncClient, engine: AsyncEngine) -> tuple[str, list[str]]:
    """Patient kc-p1 with three bookings with Dr A, made out of time order."""
    doctor_id = await add_doctor(engine, "Dr A")
    ids = [
        await make_booking(client, doctor_id, "kc-p1", S1000),
        await make_booking(client, doctor_id, "kc-p1", S0900),
        await make_booking(client, doctor_id, "kc-p1", S0930),
    ]
    p_id = await patient_id_of(client, "kc-p1")
    return p_id, ids


def starts(response: Any) -> list[str]:
    return [item["start_at"] for item in response.json()["items"]]


# --- access order ---------------------------------------------------------------


async def test_no_token_is_401(client: AsyncClient) -> None:
    response = await client.get(f"/patients/{uuid.uuid4()}/appointments")
    assert response.status_code == 401


async def test_a_doctor_is_forbidden(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    patient_id, _ = await setup(client, fresh_db)
    response = await patient_appointments(client, doctor(), patient_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_token_with_no_usable_role_is_403(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    patient_id, _ = await setup(client, fresh_db)
    headers = bearer(claims(realm_access=roles("offline_access")))
    assert (await patient_appointments(client, headers, patient_id)).status_code == 403


# --- a patient's own list ----------------------------------------------------------------


async def test_a_patient_lists_their_own_appointments_in_time_order(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    patient_id, _ = await setup(client, fresh_db)
    response = await patient_appointments(client, patient(), patient_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert starts(response) == [S0900, S0930, S1000]
    assert (body["total"], body["limit"], body["offset"]) == (3, 50, 0)
    assert all(item["patient"]["id"] == patient_id for item in body["items"])
    assert all(item["patient"]["name"] == "Pat One" for item in body["items"])
    assert all(item["doctor"]["name"] == "Dr A" for item in body["items"])
    assert all(item["status"] == "booked" for item in body["items"])
    assert "email" not in response.text
    assert "phone" not in response.text


async def test_another_patients_id_is_403(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    patient_id, _ = await setup(client, fresh_db)
    await patient_id_of(client, "kc-p2")
    response = await patient_appointments(client, patient("kc-p2"), patient_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_patient_asking_for_a_random_id_gets_403_not_404(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    await setup(client, fresh_db)
    response = await patient_appointments(client, patient(), uuid.uuid4())
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_cancelled_appointments_are_excluded(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    patient_id, ids = await setup(client, fresh_db)
    # Cancel the 09:00 booking
    assert (await cancel(client, patient(), ids[1], "Cannot attend")).status_code == 200
    after = await patient_appointments(client, patient(), patient_id)
    assert starts(after) == [S0930, S1000]
    assert after.json()["total"] == 2


# --- admin -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("permissions", "status"),
    [((), 403), (("manage_any",), 403), (("book_for_patient",), 403), (("view_any",), 200)],
)
async def test_an_admin_needs_view_any(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...], status: int
) -> None:
    patient_id, _ = await setup(client, fresh_db)
    response = await patient_appointments(client, admin(*permissions), patient_id)
    assert response.status_code == status, response.text


async def test_an_admin_with_view_any_gets_404_for_an_unknown_patient(
    client: AsyncClient,
) -> None:
    response = await patient_appointments(client, admin("view_any"), uuid.uuid4())
    assert response.status_code == 404
    assert response.json()["code"] == "PATIENT_NOT_FOUND"


async def test_a_refused_admin_learns_nothing_about_ids(client: AsyncClient) -> None:
    response = await patient_appointments(client, admin(), uuid.uuid4())
    assert response.status_code == 403  # not 404


# --- paging ----------------------------------------------------------------------------


async def test_paging_keeps_order_and_reports_the_total(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    patient_id, _ = await setup(client, fresh_db)
    first = await patient_appointments(client, patient(), patient_id, {"limit": 2})
    second = await patient_appointments(client, patient(), patient_id, {"limit": 2, "offset": 2})
    assert starts(first) == [S0900, S0930]
    assert starts(second) == [S1000]
    assert first.json()["total"] == second.json()["total"] == 3


# --- bad parameters --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"limit": 0}, "VALIDATION_ERROR"),
        ({"limit": 101}, "VALIDATION_ERROR"),
        ({"offset": -1}, "VALIDATION_ERROR"),
    ],
)
async def test_bad_parameters_are_422(
    client: AsyncClient, fresh_db: AsyncEngine, params: dict[str, Any], code: str
) -> None:
    patient_id, _ = await setup(client, fresh_db)
    response = await patient_appointments(client, patient(), patient_id, params)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
