import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import Appointment, Doctor, Patient

# 06:00 UTC = 09:00 Nairobi: aligned to a 30-minute boundary.
START = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)


async def make_doctor(conn: AsyncConnection, external_ref: str | None = None) -> uuid.UUID:
    result = await conn.execute(
        insert(Doctor).values(name="Dr Test", external_ref=external_ref).returning(Doctor.id)
    )
    return result.scalar_one()


async def make_patient(conn: AsyncConnection) -> uuid.UUID:
    result = await conn.execute(insert(Patient).values(name="Pat Test").returning(Patient.id))
    return result.scalar_one()


async def make_appointment(
    conn: AsyncConnection,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    start_at: datetime = START,
    *,
    end_at: datetime | None = None,
    status: str = "booked",
    cancel_reason: str | None = None,
    cancelled_at: datetime | None = None,
    cancelled_by_sub: str | None = None,
) -> uuid.UUID:
    result = await conn.execute(
        insert(Appointment)
        .values(
            doctor_id=doctor_id,
            patient_id=patient_id,
            start_at=start_at,
            end_at=end_at if end_at is not None else start_at + timedelta(minutes=30),
            status=status,
            cancel_reason=cancel_reason,
            cancelled_at=cancelled_at,
            created_by_sub="test-sub",
            cancelled_by_sub=cancelled_by_sub,
        )
        .returning(Appointment.id)
    )
    return result.scalar_one()
