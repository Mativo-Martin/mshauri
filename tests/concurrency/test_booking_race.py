import asyncio

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Appointment
from tests.api.data import add_doctor
from tests.api.helpers import SLOT, patient
from tests.integration.helpers import count_rows


async def test_twenty_parallel_bookings_produce_one_winner_and_nineteen_conflicts(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """20 distinct patients book the same doctor slot simultaneously.

    Exactly one wins (201); 19 receive 409 SLOT_TAKEN. The database retains exactly one row.
    """
    doctor_id = await add_doctor(fresh_db, "Dr Concurrency")

    tasks = [
        client.post(
            "/appointments",
            json={"doctor_id": str(doctor_id), "start_at": SLOT},
            headers=patient(f"kc-p{i}"),
        )
        for i in range(1, 21)
    ]
    responses = await asyncio.gather(*tasks)

    statuses = [r.status_code for r in responses]
    assert statuses.count(201) == 1
    assert statuses.count(409) == 19

    winner = next(r for r in responses if r.status_code == 201).json()
    assert winner["doctor"]["id"] == str(doctor_id)
    assert winner["status"] == "booked"

    for r in responses:
        if r.status_code == 409:
            body = r.json()
            assert body["code"] == "SLOT_TAKEN"

    assert await count_rows(fresh_db, "appointments") == 1

    async with AsyncSession(fresh_db) as session:
        result = await session.execute(select(Appointment))
        appts = result.scalars().all()
        assert len(appts) == 1
        assert str(appts[0].id) == winner["id"]
        assert appts[0].status == "booked"
