import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.clock import utc_now
from app.models import Appointment
from app.repositories import appointments as appointment_repo
from tests.api.data import add_doctor, add_exception, link_doctor
from tests.api.helpers import (
    NEW_SLOT,
    SLOT,
    admin,
    cancel,
    doctor,
    free_starts,
    make_booking,
    patient,
    reschedule,
)

START_UTC = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)
NEW_UTC = datetime(2030, 1, 7, 6, 30, tzinfo=UTC)


async def row(engine: AsyncEngine, appointment_id: str) -> Any:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM appointments WHERE id = :id"), {"id": appointment_id}
        )
        return result.mappings().one()


async def setup(client: AsyncClient, engine: AsyncEngine) -> tuple[uuid.UUID, str]:
    doctor_id = await add_doctor(engine, "Dr A")
    return doctor_id, await make_booking(client, doctor_id)


def pin_now(app: FastAPI, moment: datetime) -> None:
    app.dependency_overrides[utc_now] = lambda: moment


# --- access order ---------------------------------------------------------------


async def test_no_token_is_401_even_with_a_bad_body(client: AsyncClient) -> None:
    response = await client.patch(f"/appointments/{uuid.uuid4()}/reschedule", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"new_start_at": "not-a-date"},
        {"new_start_at": NEW_SLOT, "doctor_id": str(uuid.uuid4())},
    ],
)
async def test_a_bad_body_is_422(client: AsyncClient, fresh_db: AsyncEngine, body: Any) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await client.patch(
        f"/appointments/{appointment_id}/reschedule", json=body, headers=patient()
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_an_unknown_appointment_is_404(client: AsyncClient) -> None:
    response = await reschedule(client, patient(), str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"


# --- the happy path -----------------------------------------------------------------


async def test_a_patient_moves_their_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    before = await free_starts(client, doctor_id)
    assert SLOT not in before
    assert NEW_SLOT in before

    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == appointment_id  # same appointment, not a new one
    assert body["status"] == "booked"
    assert body["start_at"] == NEW_SLOT
    assert body["end_at"] == "2030-01-07T10:00:00+03:00"
    assert "email" not in response.text
    assert "phone" not in response.text

    after = await free_starts(client, doctor_id)
    assert SLOT in after  # the old slot is free again
    assert NEW_SLOT not in after  # the new slot is taken


async def test_the_same_row_is_updated_and_nothing_else_changes(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    await reschedule(client, patient(), appointment_id)
    async with fresh_db.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM appointments"))).scalar_one()
    assert count == 1
    saved = await row(fresh_db, appointment_id)
    assert saved["start_at"] == NEW_UTC
    assert saved["end_at"] == datetime(2030, 1, 7, 7, 0, tzinfo=UTC)
    assert saved["status"] == "booked"
    assert saved["created_by_sub"] == "kc-p1"
    assert saved["cancelled_by_sub"] is None
    assert saved["cancel_reason"] is None


# --- conflicts and state -------------------------------------------------------------


async def test_a_taken_target_is_409_and_the_original_is_untouched(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    await make_booking(client, doctor_id, sub="kc-p2", start=NEW_SLOT)

    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 409
    assert response.json()["code"] == "SLOT_TAKEN"
    saved = await row(fresh_db, appointment_id)
    assert saved["start_at"] == START_UTC
    assert saved["status"] == "booked"


@pytest.mark.parametrize("same", [SLOT, "2030-01-07T06:00:00+00:00"])
async def test_the_same_slot_is_409(client: AsyncClient, fresh_db: AsyncEngine, same: str) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await reschedule(client, patient(), appointment_id, same)
    assert response.status_code == 409
    assert response.json()["code"] == "SAME_SLOT"


async def test_a_cancelled_appointment_cannot_be_moved(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    assert (await cancel(client, patient(), appointment_id)).status_code == 200
    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 409
    assert response.json()["code"] == "APPOINTMENT_CANCELLED"


async def test_cancelled_is_reported_before_same_slot(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    await cancel(client, patient(), appointment_id)
    response = await reschedule(client, patient(), appointment_id, SLOT)
    assert response.json()["code"] == "APPOINTMENT_CANCELLED"


@pytest.mark.parametrize("minutes_after_start", [0, 1, 600])
async def test_a_started_appointment_cannot_be_moved(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine, minutes_after_start: int
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    pin_now(
        app,
        datetime(2030, 1, 7, 6, 0, tzinfo=UTC).replace(
            minute=minutes_after_start % 60, hour=6 + minutes_after_start // 60
        ),
    )
    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 409
    assert response.json()["code"] == "APPOINTMENT_IN_PAST"
    assert (await row(fresh_db, appointment_id))["start_at"] == START_UTC


async def test_started_is_reported_before_a_bad_target(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    pin_now(app, datetime(2030, 1, 7, 6, 5, tzinfo=UTC))
    response = await reschedule(client, patient(), appointment_id, "2030-01-07T09:10:00+03:00")
    assert response.json()["code"] == "APPOINTMENT_IN_PAST"


# --- the target obeys the booking rules (D6: no drift) -------------------------------


@pytest.mark.parametrize(
    ("target", "now", "status", "code"),
    [
        ("2030-01-07T09:10:00+03:00", None, 422, "SLOT_MISALIGNED"),
        ("2029-12-31T09:00:00+03:00", None, 422, "SLOT_IN_PAST"),
        ("2030-01-07T13:00:00+03:00", None, 422, "OUTSIDE_WORKING_HOURS"),
        ("2030-06-03T09:00:00+03:00", None, 422, "BEYOND_BOOKING_HORIZON"),
        ("2030-01-07T09:30:00", None, 422, "NAIVE_DATETIME"),
        (NEW_SLOT, datetime(2030, 1, 7, 5, 45, tzinfo=UTC), 422, "SLOT_TOO_SOON"),
    ],
)
async def test_target_errors_match_booking(
    app: FastAPI,
    client: AsyncClient,
    fresh_db: AsyncEngine,
    target: str,
    now: datetime | None,
    status: int,
    code: str,
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    if now is not None:
        pin_now(app, now)
    booked = await client.post(
        "/appointments",
        json={"doctor_id": str(doctor_id), "start_at": target},
        headers=patient("kc-p2"),
    )
    moved = await reschedule(client, patient(), appointment_id, target)
    assert (booked.status_code, booked.json()["code"]) == (status, code)
    assert (moved.status_code, moved.json()["code"]) == (status, code)
    assert (await row(fresh_db, appointment_id))["start_at"] == START_UTC


async def test_leave_blocks_the_target_like_booking(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    await add_exception(
        fresh_db,
        doctor_id,
        datetime(2030, 1, 7, 6, 30, tzinfo=UTC),
        datetime(2030, 1, 7, 7, 0, tzinfo=UTC),
    )
    booked = await client.post(
        "/appointments",
        json={"doctor_id": str(doctor_id), "start_at": NEW_SLOT},
        headers=patient("kc-p2"),
    )
    moved = await reschedule(client, patient(), appointment_id)
    assert (booked.status_code, booked.json()["code"]) == (422, "OUTSIDE_WORKING_HOURS")
    assert (moved.status_code, moved.json()["code"]) == (422, "OUTSIDE_WORKING_HOURS")


async def test_an_inactive_doctor_blocks_the_move_like_booking(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    async with fresh_db.begin() as conn:
        await conn.execute(
            text("UPDATE doctors SET is_active = false WHERE id = :id"), {"id": doctor_id}
        )
    booked = await client.post(
        "/appointments",
        json={"doctor_id": str(doctor_id), "start_at": NEW_SLOT},
        headers=patient("kc-p2"),
    )
    moved = await reschedule(client, patient(), appointment_id)
    assert (booked.status_code, booked.json()["code"]) == (409, "DOCTOR_UNAVAILABLE")
    assert (moved.status_code, moved.json()["code"]) == (409, "DOCTOR_UNAVAILABLE")


# --- who may move what ---------------------------------------------------------------


async def test_another_patient_is_forbidden(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await reschedule(client, patient("kc-p2"), appointment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert (await row(fresh_db, appointment_id))["start_at"] == START_UTC


async def test_a_doctor_moves_an_appointment_on_their_own_schedule(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    await link_doctor(fresh_db, doctor_id, "kc-doc1")
    response = await reschedule(client, doctor(), appointment_id)
    assert response.status_code == 200, response.text
    assert response.json()["start_at"] == NEW_SLOT


async def test_a_doctor_cannot_move_another_doctors_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    other = await add_doctor(fresh_db, "Dr B")
    await link_doctor(fresh_db, other, "kc-doc2")
    response = await reschedule(client, doctor("kc-doc2"), appointment_id)
    assert response.status_code == 403
    assert (await row(fresh_db, appointment_id))["start_at"] == START_UTC


@pytest.mark.parametrize(
    ("permissions", "status"),
    [((), 403), (("view_any",), 403), (("book_for_patient",), 403), (("manage_any",), 200)],
)
async def test_an_admin_needs_manage_any(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...], status: int
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await reschedule(client, admin(*permissions), appointment_id)
    assert response.status_code == status, response.text


async def test_a_refused_admin_learns_nothing_about_ids(client: AsyncClient) -> None:
    response = await reschedule(client, admin("view_any"), str(uuid.uuid4()))
    assert response.status_code == 403  # not 404


# --- deadlock retry (plan D13); the real race is Step 9 ------------------------------


class FakeDeadlock(Exception):
    sqlstate = "40P01"


def deadlock() -> DBAPIError:
    return DBAPIError("UPDATE appointments", {}, FakeDeadlock("deadlock detected"))


async def test_one_deadlock_is_retried_and_the_move_succeeds(
    client: AsyncClient, fresh_db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    real = appointment_repo.move_appointment
    calls = 0

    async def flaky(
        session: AsyncSession, appointment_id: uuid.UUID, new_start_at: datetime
    ) -> Appointment:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise deadlock()
        return await real(session, appointment_id, new_start_at)

    monkeypatch.setattr(appointment_repo, "move_appointment", flaky)
    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 200, response.text
    assert calls == 2
    assert (await row(fresh_db, appointment_id))["start_at"] == NEW_UTC


async def test_two_deadlocks_in_a_row_become_409_slot_taken(
    client: AsyncClient, fresh_db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    calls = 0

    async def always(
        session: AsyncSession, appointment_id: uuid.UUID, new_start_at: datetime
    ) -> Appointment:
        nonlocal calls
        calls += 1
        raise deadlock()

    monkeypatch.setattr(appointment_repo, "move_appointment", always)
    response = await reschedule(client, patient(), appointment_id)
    assert response.status_code == 409
    assert response.json()["code"] == "SLOT_TAKEN"
    assert calls == 2  # one try, one retry, then give up
    assert (await row(fresh_db, appointment_id))["start_at"] == START_UTC
