import uuid
from datetime import UTC, datetime, time

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import utc_now
from tests.api.data import EVERY_DAY_9_TO_12, add_doctor, add_exception, book
from tests.unit.auth_helpers import bearer

# Monday 2030-01-07, 09:00-12:00 Nairobi = 06:00-09:00 UTC: six slots.
MONDAY = "2030-01-07"
ALL_SIX = [datetime(2030, 1, 7, 6 + n // 2, 30 * (n % 2), tzinfo=UTC) for n in range(6)]


async def fetch(client: AsyncClient, doctor_id: uuid.UUID, day: str = MONDAY):  # type: ignore[no-untyped-def]
    return await client.get(
        f"/doctors/{doctor_id}/availability", params={"date": day}, headers=bearer()
    )


async def starts(client: AsyncClient, doctor_id: uuid.UUID, day: str = MONDAY) -> list[datetime]:
    response = await fetch(client, doctor_id, day)
    assert response.status_code == 200, response.text
    return [datetime.fromisoformat(s["start_at"]) for s in response.json()["slots"]]


async def test_a_working_day_offers_every_slot(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    assert await starts(client, doctor_id) == ALL_SIX


async def test_response_shape_and_clinic_local_offset(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    body = (await fetch(client, doctor_id)).json()
    assert set(body) == {"doctor_id", "date", "timezone", "slots"}
    assert body["date"] == MONDAY
    assert body["timezone"] == "Africa/Nairobi"
    first = body["slots"][0]
    assert set(first) == {"start_at", "end_at"}
    assert first["start_at"] == "2030-01-07T09:00:00+03:00"
    assert first["end_at"] == "2030-01-07T09:30:00+03:00"


async def test_a_booked_slot_disappears(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    await book(fresh_db, doctor_id, ALL_SIX[1])
    assert await starts(client, doctor_id) == [ALL_SIX[0], *ALL_SIX[2:]]


async def test_a_cancelled_slot_is_offered_again(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    await book(fresh_db, doctor_id, ALL_SIX[1], cancelled=True)
    assert await starts(client, doctor_id) == ALL_SIX


async def test_another_doctors_booking_does_not_block_this_doctor(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    mine = await add_doctor(fresh_db, "Dr Mine")
    other = await add_doctor(fresh_db, "Dr Other")
    await book(fresh_db, other, ALL_SIX[0])
    assert await starts(client, mine) == ALL_SIX


async def test_leave_hides_overlapping_slots_only(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    # 07:00-08:00 UTC blocks the 07:00 and 07:30 slots; the 08:00 slot only touches the edge.
    await add_exception(
        fresh_db,
        doctor_id,
        datetime(2030, 1, 7, 7, 0, tzinfo=UTC),
        datetime(2030, 1, 7, 8, 0, tzinfo=UTC),
    )
    assert await starts(client, doctor_id) == [ALL_SIX[0], ALL_SIX[1], ALL_SIX[4], ALL_SIX[5]]


async def test_a_multi_day_closure_blocks_the_whole_day(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    await add_exception(
        fresh_db,
        doctor_id,
        datetime(2030, 1, 6, 0, 0, tzinfo=UTC),
        datetime(2030, 1, 9, 0, 0, tzinfo=UTC),
        "closure",
    )
    assert await starts(client, doctor_id) == []


async def test_a_day_without_a_schedule_is_empty_not_an_error(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)  # Mondays only
    assert await starts(client, doctor_id, "2030-01-08") == []  # Tuesday


async def test_split_shifts_are_both_offered(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(
        fresh_db, windows=((0, time(9), time(10)), (0, time(14), time(15)))
    )
    assert await starts(client, doctor_id) == [
        datetime(2030, 1, 7, 6, 0, tzinfo=UTC),
        datetime(2030, 1, 7, 6, 30, tzinfo=UTC),
        datetime(2030, 1, 7, 11, 0, tzinfo=UTC),
        datetime(2030, 1, 7, 11, 30, tzinfo=UTC),
    ]


async def test_the_minimum_lead_time_hides_slots_that_start_too_soon(
    app: FastAPI, client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    app.dependency_overrides[utc_now] = lambda: datetime(2030, 1, 7, 5, 30, tzinfo=UTC)
    # Default lead time is 60 minutes: earliest bookable start is 06:30 UTC.
    assert await starts(client, doctor_id) == ALL_SIX[1:]


async def test_past_dates_are_empty(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db, windows=EVERY_DAY_9_TO_12)
    assert await starts(client, doctor_id, "2029-12-31") == []


async def test_the_horizon_includes_its_last_day_and_refuses_the_next(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db, windows=EVERY_DAY_9_TO_12)
    assert len(await starts(client, doctor_id, "2030-04-01")) == 6  # today + 90 days
    response = await fetch(client, doctor_id, "2030-04-02")  # today + 91 days
    assert response.status_code == 422
    assert response.json()["code"] == "BEYOND_BOOKING_HORIZON"


async def test_unknown_doctor_is_404(client: AsyncClient) -> None:
    response = await fetch(client, uuid.uuid4())
    assert response.status_code == 404
    assert response.json()["code"] == "DOCTOR_NOT_FOUND"


async def test_inactive_doctor_is_409_doctor_unavailable(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db, active=False)
    response = await fetch(client, doctor_id)
    assert response.status_code == 409
    assert response.json()["code"] == "DOCTOR_UNAVAILABLE"


async def test_bad_or_missing_date_is_422(client: AsyncClient, fresh_db: AsyncEngine) -> None:
    doctor_id = await add_doctor(fresh_db)
    url = f"/doctors/{doctor_id}/availability"
    for params in ({}, {"date": "tomorrow"}, {"date": "2030-02-30"}, {"date": "07/01/2030"}):
        response = await client.get(url, params=params, headers=bearer())
        assert response.status_code == 422, params
        assert response.json()["code"] == "VALIDATION_ERROR"


async def test_authentication_comes_before_validation(client: AsyncClient) -> None:
    response = await client.get(
        f"/doctors/{uuid.uuid4()}/availability", params={"date": "not-a-date"}
    )
    assert response.status_code == 401


async def test_availability_exposes_no_patient_information(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    doctor_id = await add_doctor(fresh_db)
    await book(fresh_db, doctor_id, ALL_SIX[0])
    assert "patient" not in (await fetch(client, doctor_id)).text.lower()
