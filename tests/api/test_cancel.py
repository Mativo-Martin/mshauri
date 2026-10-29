import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import utc_now
from tests.api.data import add_doctor, link_doctor
from tests.api.helpers import SLOT, admin, cancel, doctor, make_booking, patient
from tests.unit.auth_helpers import bearer, claims, roles

START_UTC = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)


async def row(engine: AsyncEngine, appointment_id: str) -> Any:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM appointments WHERE id = :id"), {"id": appointment_id}
        )
        return result.mappings().one()


async def setup(client: AsyncClient, engine: AsyncEngine) -> tuple[uuid.UUID, str]:
    doctor_id = await add_doctor(engine, "Dr A")
    return doctor_id, await make_booking(client, doctor_id)


# --- access order ---------------------------------------------------------------


async def test_no_token_is_401_even_with_a_bad_body(client: AsyncClient) -> None:
    response = await client.patch(f"/appointments/{uuid.uuid4()}/cancel", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_a_token_with_no_usable_role_is_403(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    headers = bearer(claims(realm_access=roles("offline_access")))
    assert (await cancel(client, headers, appointment_id)).status_code == 403


# --- the patient's own cancellation -------------------------------------------------


async def test_a_patient_cancels_their_own_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, patient(), appointment_id, "Feeling better")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == appointment_id
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Feeling better"
    assert body["cancelled_at"] is not None
    assert body["start_at"] == SLOT  # nothing else changed
    assert "email" not in response.text
    assert "phone" not in response.text


async def test_the_row_records_who_cancelled_and_keeps_its_history(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    await cancel(client, patient(), appointment_id)
    saved = await row(fresh_db, appointment_id)
    assert saved["status"] == "cancelled"
    assert saved["cancelled_by_sub"] == "kc-p1"
    assert saved["created_by_sub"] == "kc-p1"
    assert saved["start_at"] == START_UTC
    assert saved["cancel_reason"] == "Cannot attend"


async def test_the_slot_reopens_and_someone_else_can_book_it(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    url = f"/doctors/{doctor_id}/availability"
    before = (await client.get(url, params={"date": "2030-01-07"}, headers=patient())).json()[
        "slots"
    ]
    await cancel(client, patient(), appointment_id)
    after = (await client.get(url, params={"date": "2030-01-07"}, headers=patient())).json()[
        "slots"
    ]
    assert len(after) == len(before) + 1
    assert SLOT in [s["start_at"] for s in after]
    rebook = await client.post(
        "/appointments",
        json={"doctor_id": str(doctor_id), "start_at": SLOT},
        headers=patient("kc-p2"),
    )
    assert rebook.status_code == 201


async def test_the_reason_is_trimmed(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, patient(), appointment_id, "  Travelling  ")
    assert response.json()["cancel_reason"] == "Travelling"


@pytest.mark.parametrize("reason", ["", "   ", None, 42, "x" * 501])
async def test_a_missing_or_bad_reason_is_422_and_changes_nothing(
    client: AsyncClient, fresh_db: AsyncEngine, reason: Any
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, patient(), appointment_id, reason)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await row(fresh_db, appointment_id))["status"] == "booked"


async def test_an_empty_body_and_unknown_fields_are_422(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    url = f"/appointments/{appointment_id}/cancel"
    assert (await client.patch(url, json={}, headers=patient())).status_code == 422
    extra = await client.patch(url, json={"reason": "x", "status": "booked"}, headers=patient())
    assert extra.status_code == 422


# --- state rules ----------------------------------------------------------------------


async def test_a_second_cancel_is_409_and_keeps_the_first_reason(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    await cancel(client, patient(), appointment_id, "First reason")
    again = await cancel(client, patient(), appointment_id, "Second reason")
    assert again.status_code == 409
    assert again.json()["code"] == "ALREADY_CANCELLED"
    assert (await row(fresh_db, appointment_id))["cancel_reason"] == "First reason"


async def test_cancelling_shortly_before_the_start_is_allowed(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """The booking lead time does not apply to cancellation."""
    _, appointment_id = await setup(client, fresh_db)
    app.dependency_overrides[utc_now] = lambda: datetime(2030, 1, 7, 5, 50, tzinfo=UTC)
    assert (await cancel(client, patient(), appointment_id)).status_code == 200


@pytest.mark.parametrize("minutes_after_start", [0, 1, 600])
async def test_a_started_appointment_cannot_be_cancelled(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine, minutes_after_start: int
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    moment = datetime(2030, 1, 7, 6, minutes_after_start % 60, tzinfo=UTC).replace(
        hour=6 + minutes_after_start // 60
    )
    app.dependency_overrides[utc_now] = lambda: moment
    response = await cancel(client, patient(), appointment_id)
    assert response.status_code == 409
    assert response.json()["code"] == "APPOINTMENT_IN_PAST"
    assert (await row(fresh_db, appointment_id))["status"] == "booked"


async def test_five_simultaneous_cancels_have_exactly_one_winner(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    responses = await asyncio.gather(
        *(cancel(client, patient(), appointment_id, f"reason {n}") for n in range(5))
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409]
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"ALREADY_CANCELLED"}
    saved = await row(fresh_db, appointment_id)
    winner = next(r for r in responses if r.status_code == 200)
    assert saved["cancel_reason"] == winner.json()["cancel_reason"]  # one coherent final state


# --- not found, not yours -------------------------------------------------------------


async def test_unknown_appointment_is_404(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    await setup(client, fresh_db)
    response = await cancel(client, patient(), str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["code"] == "APPOINTMENT_NOT_FOUND"


async def test_malformed_id_is_422(client: AsyncClient) -> None:
    response = await cancel(client, patient(), "not-a-uuid")
    assert response.status_code == 422


async def test_another_patient_cannot_cancel_and_nothing_changes(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, patient("kc-p2"), appointment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert (await row(fresh_db, appointment_id))["status"] == "booked"


async def test_permission_roles_on_a_patient_token_grant_nothing(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    sneaky = bearer(claims(sub="kc-p2", realm_access=roles("patient", "manage_any", "view_any")))
    assert (await cancel(client, sneaky, appointment_id)).status_code == 403


# --- doctors ----------------------------------------------------------------------------


async def test_a_doctor_cancels_on_their_own_schedule(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id, appointment_id = await setup(client, fresh_db)
    await link_doctor(fresh_db, doctor_id, "kc-doc1")
    response = await cancel(client, doctor(), appointment_id, "Doctor unwell")
    assert response.status_code == 200
    assert (await row(fresh_db, appointment_id))["cancelled_by_sub"] == "kc-doc1"


async def test_a_doctor_cannot_cancel_another_doctors_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    other = await add_doctor(fresh_db, "Dr Other")
    await link_doctor(fresh_db, other, "kc-doc2")
    response = await cancel(client, doctor("kc-doc2"), appointment_id)
    assert response.status_code == 403
    assert (await row(fresh_db, appointment_id))["status"] == "booked"


async def test_an_unlinked_doctor_is_403_profile_not_provisioned(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, doctor("kc-nobody"), appointment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "PROFILE_NOT_PROVISIONED"


# --- admins -----------------------------------------------------------------------------


async def test_an_admin_with_manage_any_cancels_any_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, admin("manage_any"), appointment_id, "Clinic closed")
    assert response.status_code == 200
    assert (await row(fresh_db, appointment_id))["cancelled_by_sub"] == "kc-admin"


@pytest.mark.parametrize("permissions", [(), ("view_any",), ("book_for_patient", "view_any")])
async def test_an_admin_without_manage_any_is_refused(
    client: AsyncClient, fresh_db: AsyncEngine, permissions: tuple[str, ...]
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    response = await cancel(client, admin(*permissions), appointment_id)
    assert response.status_code == 403
    assert (await row(fresh_db, appointment_id))["status"] == "booked"


async def test_a_refused_admin_cannot_tell_whether_an_id_exists(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    _, real = await setup(client, fresh_db)
    for appointment_id in (real, str(uuid.uuid4())):
        response = await cancel(client, admin("view_any"), appointment_id, reason="")
        assert response.status_code == 403  # not 404, not 422


# --- audit --------------------------------------------------------------------------------


async def test_cancellation_is_audited_without_the_reason_or_personal_data(
    client: AsyncClient, fresh_db: AsyncEngine, caplog: Any
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        await cancel(client, patient(), appointment_id, "Private clinical detail")
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    cancelled = [e for e in entries if e["action"] == "appointment.cancel"]
    assert len(cancelled) == 1
    assert cancelled[0]["outcome"] == "success"
    assert cancelled[0]["actor"] == "kc-p1"
    assert cancelled[0]["resource_id"] == appointment_id
    assert "Private clinical detail" not in caplog.text
    assert "Pat One" not in caplog.text


async def test_a_refused_cancellation_is_audited(
    client: AsyncClient, fresh_db: AsyncEngine, caplog: Any
) -> None:
    _, appointment_id = await setup(client, fresh_db)
    with caplog.at_level(logging.INFO, logger="mshauri.audit"):
        await cancel(client, patient("kc-p2"), appointment_id)
    entries = [json.loads(r.getMessage()) for r in caplog.records if r.name == "mshauri.audit"]
    denied = [e for e in entries if e["action"] == "appointment.cancel"]
    assert [(e["outcome"], e["reason"]) for e in denied] == [("denied", "not_owner")]
