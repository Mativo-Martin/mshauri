"""Rows for API tests, committed through the engine (the app reads on other connections)."""

import uuid
from datetime import datetime, time

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models import Doctor, DoctorSchedule, ScheduleException
from tests.integration.factories import make_appointment, make_patient

MONDAY_9_TO_12 = ((0, time(9), time(12)),)  # Nairobi wall time: 06:00-09:00 UTC
EVERY_DAY_9_TO_12 = tuple((day, time(9), time(12)) for day in range(7))


async def add_doctor(
    engine: AsyncEngine,
    name: str = "Dr A",
    specialty: str | None = "General Practice",
    *,
    active: bool = True,
    windows: tuple[tuple[int, time, time], ...] = MONDAY_9_TO_12,
) -> uuid.UUID:
    async with engine.begin() as conn:
        result = await conn.execute(
            insert(Doctor)
            .values(name=name, specialty=specialty, is_active=active)
            .returning(Doctor.id)
        )
        doctor_id = result.scalar_one()
        for weekday, start, end in windows:
            await conn.execute(
                insert(DoctorSchedule).values(
                    doctor_id=doctor_id, weekday=weekday, start_time=start, end_time=end
                )
            )
    return doctor_id


async def add_exception(
    engine: AsyncEngine,
    doctor_id: uuid.UUID,
    start: datetime,
    end: datetime,
    kind: str = "leave",
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(ScheduleException).values(
                doctor_id=doctor_id, start_timestamp=start, end_timestamp=end, type=kind
            )
        )


async def book(
    engine: AsyncEngine, doctor_id: uuid.UUID, start_at: datetime, *, cancelled: bool = False
) -> None:
    async with engine.begin() as conn:
        patient_id = await make_patient(conn)
        if cancelled:
            await make_appointment(
                conn,
                doctor_id,
                patient_id,
                start_at,
                status="cancelled",
                cancel_reason="Cancelled in test",
                cancelled_at=start_at,
                cancelled_by_sub="test-sub",
            )
        else:
            await make_appointment(conn, doctor_id, patient_id, start_at)
