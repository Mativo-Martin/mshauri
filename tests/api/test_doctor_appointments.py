import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import utc_now
from tests.api.data import add_doctor, link_doctor
from tests.api.helpers import (
    SLOT,
    admin,
    cancel,
    doctor,
    doctor_appointments,
    make_booking,
    patient,
)
from tests.unit.auth_helpers import bearer, claims, roles

S0900 = SLOT
S0930 = "2030-01-07T09:30:00+03:00"
S1000 = "2030-01-07T10:00:00+03:00"


async def setup(client: AsyncClient, engine: AsyncEngine) -> tuple[uuid.UUID, list[str]]:
    """Dr A (linked to kc-doc1) with three bookings, made out of time order."""
    doctor_id = await add_doctor(engine, "Dr A")
    await link_doctor(engine, doctor_id, "kc-doc1")
    ids = [
        await make_booking(client, doctor_id, "kc-p3", S1000),
        await make_booking(client, doctor_id, "kc-p1", S0900),
        await make_booking(client, doctor_id, "kc-p2", S0930),
    ]
    return doctor_id, ids


def starts(response: Any) -> list[str]:
    return [item["start_at"] for item in response.json()["items"]]


# --- access order ---------------------------------------------------------------


async def test_no_token_is_401(client: AsyncClient) -> None:
    response = await client.get(f"/doctors/{uuid.uuid4()}/appointments")
    assert response.status_code == 401


async def test_a_patient_is_forbidden(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(client, patient(), doctor_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_token_with_no_usable_role_is_403(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    headers = bearer(claims(realm_access=roles("offline_access")))
    assert (await doctor_appointments(client, headers, doctor_id)).status_code == 403


async def test_an_unlinked_doctor_is_403_profile_not_provisioned(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(client, doctor("kc-nobody"), doctor_id)
    assert response.status_code == 403
    assert response.json()["code"] == "PROFILE_NOT_PROVISIONED"


# --- a doctor's own list ----------------------------------------------------------------


async def test_a_doctor_lists_their_own_appointments_in_time_order(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(client, doctor(), doctor_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert starts(response) == [S0900, S0930, S1000]
    assert (body["total"], body["limit"], body["offset"]) == (3, 50, 0)
    assert all(item["doctor"]["name"] == "Dr A" for item in body["items"])
    assert all(set(item["patient"]) == {"id", "name"} for item in body["items"])
    assert "email" not in response.text
    assert "phone" not in response.text


async def test_another_doctors_id_is_403(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    other = await add_doctor(fresh_db, "Dr B")
    await link_doctor(fresh_db, other, "kc-doc2")
    response = await doctor_appointments(client, doctor("kc-doc2"), doctor_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_doctor_asking_for_a_random_id_gets_403_not_404(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    await setup(client, fresh_db)
    response = await doctor_appointments(client, doctor(), uuid.uuid4())
    assert response.status_code == 403


async def test_a_doctor_can_discover_an_id_and_then_cancel_it(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    listing = await doctor_appointments(client, doctor(), doctor_id)
    first_id = listing.json()["items"][0]["id"]
    assert (await cancel(client, doctor(), first_id, "Doctor unwell")).status_code == 200
    after = await doctor_appointments(client, doctor(), doctor_id)
    assert starts(after) == [S0930, S1000]


# --- admin -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("permissions", "status"),
    [((), 403), (("manage_any",), 403), (("book_for_patient",), 403), (("view_any",), 200)],
)
async def test_an_admin_needs_view_any(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...], status: int
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(client, admin(*permissions), doctor_id)
    assert response.status_code == status, response.text


async def test_an_admin_with_view_any_gets_404_for_an_unknown_doctor(
    client: AsyncClient,
) -> None:
    response = await doctor_appointments(client, admin("view_any"), uuid.uuid4())
    assert response.status_code == 404
    assert response.json()["code"] == "DOCTOR_NOT_FOUND"


async def test_a_refused_admin_learns_nothing_about_ids(client: AsyncClient) -> None:
    response = await doctor_appointments(client, admin(), uuid.uuid4())
    assert response.status_code == 403  # not 404


# --- filters ---------------------------------------------------------------------------


async def test_status_filter(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id, ids = await setup(client, fresh_db)
    await cancel(client, doctor(), ids[1], "Cannot attend")  # the 09:00 booking
    booked = await doctor_appointments(client, doctor(), doctor_id)
    cancelled = await doctor_appointments(client, doctor(), doctor_id, {"status": "cancelled"})
    everything = await doctor_appointments(client, doctor(), doctor_id, {"status": "all"})
    assert starts(booked) == [S0930, S1000]  # default is booked only
    assert starts(cancelled) == [S0900]
    assert cancelled.json()["items"][0]["cancel_reason"] == "Cannot attend"
    assert starts(everything) == [S0900, S0930, S1000]
    assert everything.json()["total"] == 3


async def test_from_is_inclusive_and_to_is_exclusive(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    only_from = await doctor_appointments(client, doctor(), doctor_id, {"from": S0930})
    only_to = await doctor_appointments(client, doctor(), doctor_id, {"to": S1000})
    both = await doctor_appointments(client, doctor(), doctor_id, {"from": S0930, "to": S1000})
    assert starts(only_from) == [S0930, S1000]
    assert starts(only_to) == [S0900, S0930]
    assert starts(both) == [S0930]


async def test_from_defaults_to_now(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    app.dependency_overrides[utc_now] = lambda: datetime(2030, 1, 7, 6, 10, tzinfo=UTC)
    response = await doctor_appointments(client, doctor(), doctor_id)
    assert starts(response) == [S0930, S1000]  # 09:00 local (06:00 UTC) has started


async def test_a_day_with_nothing_is_an_empty_list(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(
        client,
        doctor(),
        doctor_id,
        {"from": "2030-01-08T00:00:00+03:00", "to": "2030-01-09T00:00:00+03:00"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


# --- paging ----------------------------------------------------------------------------


async def test_paging_keeps_order_and_reports_the_total(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    first = await doctor_appointments(client, doctor(), doctor_id, {"limit": 2})
    second = await doctor_appointments(client, doctor(), doctor_id, {"limit": 2, "offset": 2})
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
        ({"status": "pending"}, "VALIDATION_ERROR"),
        ({"from": "nonsense"}, "VALIDATION_ERROR"),
        ({"from": "2030-01-07T09:00:00"}, "NAIVE_DATETIME"),
        ({"to": "2030-01-07T09:00:00"}, "NAIVE_DATETIME"),
        ({"from": S1000, "to": S0900}, "VALIDATION_ERROR"),
        ({"from": S0900, "to": S0900}, "VALIDATION_ERROR"),
    ],
)
async def test_bad_parameters_are_422(
    client: AsyncClient, fresh_db: AsyncEngine, params: dict[str, Any], code: str
) -> None:
    doctor_id, _ = await setup(client, fresh_db)
    response = await doctor_appointments(client, doctor(), doctor_id, params)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
