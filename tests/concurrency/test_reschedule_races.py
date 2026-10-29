import asyncio
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Appointment
from tests.api.data import add_doctor
from tests.api.helpers import cancel, make_booking, patient, reschedule

S0900 = "2030-01-07T09:00:00+03:00"
S0930 = "2030-01-07T09:30:00+03:00"
S1000 = "2030-01-07T10:00:00+03:00"


async def test_two_appointments_rescheduling_into_one_target(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """Two appointments race to move into the same free slot.

    Exactly one wins (200); the loser receives 409 SLOT_TAKEN and keeps its original slot intact.
    """
    doctor_id = await add_doctor(fresh_db, "Dr TargetRace")
    appt_a = await make_booking(client, doctor_id, "kc-p1", S0900)
    appt_b = await make_booking(client, doctor_id, "kc-p2", S0930)

    # Both race to move into 10:00
    res_a, res_b = await asyncio.gather(
        reschedule(client, patient("kc-p1"), appt_a, S1000),
        reschedule(client, patient("kc-p2"), appt_b, S1000),
    )

    statuses = [res_a.status_code, res_b.status_code]
    assert sorted(statuses) == [200, 409]

    conflict_res = res_a if res_a.status_code == 409 else res_b
    assert conflict_res.json()["code"] == "SLOT_TAKEN"

    async with AsyncSession(fresh_db) as session:
        result = await session.execute(select(Appointment).order_by(Appointment.id))
        appts = {str(a.id): a for a in result.scalars().all()}
        assert len(appts) == 2

        if res_a.status_code == 200:
            assert appts[appt_a].start_at == datetime(2030, 1, 7, 7, 0, tzinfo=UTC)  # 10:00 EAT
            assert appts[appt_b].start_at == datetime(2030, 1, 7, 6, 30, tzinfo=UTC)  # 09:30 EAT
        else:
            assert appts[appt_b].start_at == datetime(2030, 1, 7, 7, 0, tzinfo=UTC)  # 10:00 EAT
            assert appts[appt_a].start_at == datetime(2030, 1, 7, 6, 0, tzinfo=UTC)  # 09:00 EAT

        assert all(a.status == "booked" for a in appts.values())


async def test_concurrent_slot_swap_resolves_cleanly_without_500(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """Two appointments attempt to swap slots concurrently.

    Postgres detects potential deadlocks (40P01), which our service catches and retries once (D13).
    Guarantees: No 500 error; all responses are 200 or 409; appointment count stays 2;
    and the database never has duplicate booked slots.
    """
    doctor_id = await add_doctor(fresh_db, "Dr SwapRace")
    appt_a = await make_booking(client, doctor_id, "kc-p1", S0900)
    appt_b = await make_booking(client, doctor_id, "kc-p2", S0930)

    # Concurrently attempt swap: A -> 09:30, B -> 09:00
    res_a, res_b = await asyncio.gather(
        reschedule(client, patient("kc-p1"), appt_a, S0930),
        reschedule(client, patient("kc-p2"), appt_b, S0900),
    )

    for res in (res_a, res_b):
        assert res.status_code in (200, 409), f"Unexpected status {res.status_code}: {res.text}"
        if res.status_code == 409:
            assert res.json()["code"] == "SLOT_TAKEN"

    async with AsyncSession(fresh_db) as session:
        result = await session.execute(select(Appointment))
        appts = result.scalars().all()
        assert len(appts) == 2
        assert all(a.status == "booked" for a in appts)
        # Invariant: the two appointments must never share the same start time
        starts = {a.start_at for a in appts}
        assert len(starts) == 2


async def test_concurrent_cancel_and_reschedule_on_same_appointment(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """One caller cancels while another reschedules the same appointment concurrently.

    They serialize on the row lock (SELECT FOR UPDATE).
    If cancel commits first: cancel is 200, reschedule is 409 APPOINTMENT_CANCELLED.
    If reschedule commits first: reschedule is 200, cancel is 200 .
    In either interleaving, the database state is consistent and no 500 error occurs.
    """
    doctor_id = await add_doctor(fresh_db, "Dr CancelReschedRace")
    appt_id = await make_booking(client, doctor_id, "kc-p1", S0900)

    res_cancel, res_resched = await asyncio.gather(
        cancel(client, patient("kc-p1"), appt_id, "Patient unwell"),
        reschedule(client, patient("kc-p1"), appt_id, S0930),
    )

    statuses = [res_cancel.status_code, res_resched.status_code]
    assert statuses in ([200, 409], [200, 200]), f"Unexpected statuses: {statuses}"

    if res_resched.status_code == 409:
        assert res_resched.json()["code"] == "APPOINTMENT_CANCELLED"

    async with AsyncSession(fresh_db) as session:
        result = await session.execute(select(Appointment).where(Appointment.id == appt_id))
        appt = result.scalar_one()
        assert appt.status == "cancelled"
        assert appt.cancel_reason == "Patient unwell"


async def test_reschedule_after_cancelled_returns_conflict(
    client: AsyncClient, fresh_db: AsyncEngine
) -> None:
    """An appointment cancelled prior to reschedule always yields 409 APPOINTMENT_CANCELLED."""
    doctor_id = await add_doctor(fresh_db, "Dr CancelledResched")
    appt_id = await make_booking(client, doctor_id, "kc-p1", S0900)

    res_cancel = await cancel(client, patient("kc-p1"), appt_id, "Cancelled")
    assert res_cancel.status_code == 200

    res_resched = await reschedule(client, patient("kc-p1"), appt_id, S0930)
    assert res_resched.status_code == 409
    assert res_resched.json()["code"] == "APPOINTMENT_CANCELLED"
