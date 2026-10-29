import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import utc_now
from tests.api.data import add_doctor, add_exception, book
from tests.integration.helpers import count_rows
from tests.unit.auth_helpers import bearer, claims, roles

# Monday 2030-01-07 09:00 Nairobi = 06:00 UTC. The pinned "now" is 2030-01-01.
SLOT = "2030-01-07T09:00:00+03:00"
SLOT_UTC = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)


def patient(sub: str = "kc-p1") -> dict[str, str]:
    return bearer(claims(sub=sub))


def admin(*permissions: str, sub: str = "kc-admin") -> dict[str, str]:
    return bearer(claims(sub=sub, realm_access=roles("admin", *permissions)))


async def post(
    client: AsyncClient,
    headers: dict[str, str],
    doctor_id: uuid.UUID | str,
    start: Any = SLOT,
    **extra: Any,
) -> Response:
    body = {"doctor_id": str(doctor_id), "start_at": start, **extra}
    return await client.post("/appointments", json=body, headers=headers)


async def patient_id_of(client: AsyncClient, sub: str) -> str:
    return str((await client.get("/me", headers=patient(sub))).json()["patient_id"])


# --- access ------------------------------------------------------------------


async def test_no_token_is_401_even_with_a_bad_body(client: AsyncClient) -> None:
    response = await client.post("/appointments", json={"nonsense": True})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_a_doctor_cannot_book(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    headers = bearer(claims(realm_access=roles("doctor")))
    response = await post(client, headers, doctor_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_a_token_with_no_usable_role_cannot_book(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, bearer(claims(realm_access=roles("offline_access"))), doctor_id)
    assert response.status_code == 403


# --- the happy path ------------------------------------------------------------


async def test_a_patient_books_without_calling_me_first(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db, "Dr A")
    response = await post(client, patient(), doctor_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "doctor",
        "patient",
        "start_at",
        "end_at",
        "status",
        "created_at",
        "updated_at",
    }
    assert body["status"] == "booked"
    assert body["doctor"] == {"id": str(doctor_id), "name": "Dr A"}
    assert body["patient"]["name"] == "Pat One"
    assert body["start_at"] == "2030-01-07T09:00:00+03:00"
    assert body["end_at"] == "2030-01-07T09:30:00+03:00"
    assert await count_rows(fresh_db, "patients") == 1
    assert await count_rows(fresh_db, "appointments") == 1


async def test_the_response_has_no_contact_details(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, patient(), doctor_id)
    assert "example.test" not in response.text
    assert "email" not in response.text
    assert "phone" not in response.text
    assert "cancel" not in response.text


async def test_who_booked_is_recorded(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    await post(client, patient("kc-recorded"), doctor_id)
    async with fresh_db.connect() as conn:
        created_by = (
            await conn.execute(text("SELECT created_by_sub FROM appointments"))
        ).scalar_one()
    assert created_by == "kc-recorded"


async def test_the_slot_leaves_availability_after_booking(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    url = f"/doctors/{doctor_id}/availability"
    before = (await client.get(url, params={"date": "2030-01-07"}, headers=patient())).json()[
        "slots"
    ]
    await post(client, patient(), doctor_id)
    after = (await client.get(url, params={"date": "2030-01-07"}, headers=patient())).json()[
        "slots"
    ]
    assert len(after) == len(before) - 1
    assert SLOT not in [s["start_at"] for s in after]


async def test_any_offset_for_the_same_instant_works(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, patient(), doctor_id, "2030-01-07T06:00:00Z")
    assert response.status_code == 201
    assert response.json()["start_at"] == "2030-01-07T09:00:00+03:00"


async def test_a_cancelled_slot_can_be_booked_again(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    await book(fresh_db, doctor_id, SLOT_UTC, cancelled=True)
    assert (await post(client, patient(), doctor_id)).status_code == 201


# --- schedule rules: the same codes as validate_slot ---------------------------

RULE_CASES = [
    ("2030-01-07T09:15:00+03:00", "SLOT_MISALIGNED", None),
    ("2029-12-31T09:00:00+03:00", "SLOT_IN_PAST", None),
    ("2030-01-07T09:00:00+03:00", "SLOT_TOO_SOON", datetime(2030, 1, 7, 5, 30, tzinfo=UTC)),
    ("2030-04-02T09:00:00+03:00", "BEYOND_BOOKING_HORIZON", None),
    ("2030-01-07T13:00:00+03:00", "OUTSIDE_WORKING_HOURS", None),
    ("2030-01-07T12:00:00+03:00", "OUTSIDE_WORKING_HOURS", None),  # window ends 12:00
    ("2030-01-08T09:00:00+03:00", "OUTSIDE_WORKING_HOURS", None),  # Tuesday: no schedule
]


@pytest.mark.parametrize(("start", "code", "now"), RULE_CASES)
async def test_schedule_rules_are_enforced(
    app: FastAPI,
    client: AsyncClient,
    fresh_db: AsyncEngine,
    start: str,
    code: str,
    now: datetime | None,
) -> None:
    doctor_id = await add_doctor(fresh_db)
    if now is not None:
        app.dependency_overrides[utc_now] = lambda: now
    response = await post(client, patient(), doctor_id, start)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
    assert await count_rows(fresh_db, "appointments") == 0


async def test_leave_blocks_booking_and_the_message_says_why(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    await add_exception(
        fresh_db,
        doctor_id,
        datetime(2030, 1, 7, 6, 0, tzinfo=UTC),
        datetime(2030, 1, 7, 7, 0, tzinfo=UTC),
    )
    response = await post(client, patient(), doctor_id)
    assert response.status_code == 422
    assert response.json()["code"] == "OUTSIDE_WORKING_HOURS"
    assert "leave" in response.json()["detail"]


async def test_a_naive_datetime_is_naive_datetime_not_a_generic_error(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, patient(), doctor_id, "2030-01-07T09:00:00")
    assert response.status_code == 422
    assert response.json()["code"] == "NAIVE_DATETIME"


@pytest.mark.parametrize("start", ["tomorrow", 12345, None])
async def test_an_unreadable_datetime_is_a_validation_error(
    client: AsyncClient, fresh_db: AsyncEngine, start: Any
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, patient(), doctor_id, start)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_unknown_body_fields_are_refused(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, patient(), doctor_id, status="cancelled")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert await count_rows(fresh_db, "appointments") == 0


# --- doctors ---------------------------------------------------------------------


async def test_inactive_doctor_is_409_doctor_unavailable(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db, active=False)
    response = await post(client, patient(), doctor_id)
    assert response.status_code == 409
    assert response.json()["code"] == "DOCTOR_UNAVAILABLE"


async def test_unknown_doctor_is_404_before_any_schedule_rule(client: AsyncClient) -> None:
    response = await post(client, patient(), uuid.uuid4(), "2029-01-01T09:15:00+03:00")
    assert response.status_code == 404
    assert response.json()["code"] == "DOCTOR_NOT_FOUND"


# --- double booking and replay ----------------------------------------------------


async def test_a_second_patient_gets_slot_taken_and_the_first_booking_stays(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    first = await post(client, patient("kc-first"), doctor_id)
    second = await post(client, patient("kc-second"), doctor_id)
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "SLOT_TAKEN"
    assert await count_rows(fresh_db, "appointments") == 1
    async with fresh_db.connect() as conn:
        created_by = (
            await conn.execute(text("SELECT created_by_sub FROM appointments"))
        ).scalar_one()
    assert created_by == "kc-first"


async def test_an_identical_replay_returns_the_same_appointment_with_200(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    first = await post(client, patient(), doctor_id)
    replay = await post(client, patient(), doctor_id, "2030-01-07T06:00:00Z")
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert await count_rows(fresh_db, "appointments") == 1


async def test_the_same_patient_cannot_replay_onto_another_doctors_slot(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    one = await add_doctor(fresh_db, "Dr One")
    two = await add_doctor(fresh_db, "Dr Two")
    assert (await post(client, patient(), one)).status_code == 201
    # Overlapping appointments across doctors are allowed (plan section 18).
    assert (await post(client, patient(), two)).status_code == 201
    assert await count_rows(fresh_db, "appointments") == 2


async def test_ten_simultaneous_bookings_of_one_slot_have_exactly_one_winner(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    responses = await asyncio.gather(
        *(post(client, patient(f"kc-race-{n}"), doctor_id) for n in range(10))
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * 9, statuses
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"SLOT_TAKEN"}
    assert await count_rows(fresh_db, "appointments") == 1


# --- patient identity ---------------------------------------------------------------


async def test_a_patient_cannot_book_for_someone_else(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    other_id = await patient_id_of(client, "kc-other")
    response = await post(client, patient("kc-p1"), doctor_id, patient_id=other_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert await count_rows(fresh_db, "appointments") == 0


async def test_a_patient_may_name_themselves(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    own_id = await patient_id_of(client, "kc-p1")
    response = await post(client, patient("kc-p1"), doctor_id, patient_id=own_id)
    assert response.status_code == 201
    assert response.json()["patient"]["id"] == own_id


# --- admins ---------------------------------------------------------------------------


async def test_an_admin_with_permission_books_for_a_patient(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    target = await patient_id_of(client, "kc-target")
    response = await post(client, admin("book_for_patient"), doctor_id, patient_id=target)
    assert response.status_code == 201, response.text
    assert response.json()["patient"]["id"] == target
    async with fresh_db.connect() as conn:
        created_by = (
            await conn.execute(text("SELECT created_by_sub FROM appointments"))
        ).scalar_one()
    assert created_by == "kc-admin"  # the admin is on record, not the patient


@pytest.mark.parametrize("permissions", [(), ("view_any",), ("manage_any", "view_any")])
async def test_an_admin_without_book_for_patient_is_refused(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...]
) -> None:
    doctor_id = await add_doctor(fresh_db)
    target = await patient_id_of(client, "kc-target")
    response = await post(client, admin(*permissions), doctor_id, patient_id=target)
    assert response.status_code == 403
    assert await count_rows(fresh_db, "appointments") == 0


async def test_permission_is_checked_before_the_missing_patient_id(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, admin(), doctor_id)  # no permission and no patient_id
    assert response.status_code == 403


async def test_an_admin_must_name_the_patient(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(client, admin("book_for_patient"), doctor_id)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_an_admin_naming_an_unknown_patient_gets_404(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    response = await post(
        client, admin("book_for_patient"), doctor_id, patient_id=str(uuid.uuid4())
    )
    assert response.status_code == 404
    assert response.json()["code"] == "PATIENT_NOT_FOUND"


async def test_an_anonymised_patient_cannot_be_booked_for(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    target = await patient_id_of(client, "kc-gone")
    async with fresh_db.begin() as conn:
        await conn.execute(
            text("UPDATE patients SET anonymized_at = now(), keycloak_sub = NULL WHERE id = :id"),
            {"id": target},
        )
    response = await post(client, admin("book_for_patient"), doctor_id, patient_id=target)
    assert response.status_code == 404
    assert response.json()["code"] == "PATIENT_NOT_FOUND"


# --- audit ------------------------------------------------------------------------------


async def test_booking_is_audited_without_personal_data(
    client: AsyncClient, fresh_db: AsyncEngine, caplog: Any
) -> None:
    doctor_id = await add_doctor(fresh_db)
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        response = await post(client, patient("kc-audited"), doctor_id)
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    booked = [e for e in entries if e["action"] == "appointment.book"]
    assert len(booked) == 1
    assert booked[0]["outcome"] == "success"
    assert booked[0]["actor"] == "kc-audited"
    assert booked[0]["resource_type"] == "appointment"
    assert booked[0]["resource_id"] == response.json()["id"]
    assert "Pat One" not in caplog.text
    assert "example.test" not in caplog.text


async def test_a_refused_booking_is_audited(
    client: AsyncClient, fresh_db: AsyncEngine, caplog: Any
) -> None:
    doctor_id = await add_doctor(fresh_db)
    other_id = await patient_id_of(client, "kc-other")
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        await post(client, patient("kc-p1"), doctor_id, patient_id=other_id)
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    denied = [e for e in entries if e["action"] == "appointment.book"]
    assert [e["outcome"] for e in denied] == ["denied"]
    assert denied[0]["reason"] == "other_patient"
