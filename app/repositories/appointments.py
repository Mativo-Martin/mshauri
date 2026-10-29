import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment

# The double-booking guard (plan section 6). Matched by name, never by message wording alone.
SLOT_INDEX = "uq_appointments_doctor_start_booked"
SLOT_LENGTH = timedelta(minutes=30)


async def insert_booked(
    session: AsyncSession,
    doctor_id: uuid.UUID,
    patient_id: uuid.UUID,
    start_at: datetime,
    created_by_sub: str,
) -> Appointment:
    """Insert a booked appointment. The database decides whether the slot is free."""
    start = start_at.astimezone(UTC)
    result = await session.execute(
        insert(Appointment)
        .values(
            doctor_id=doctor_id,
            patient_id=patient_id,
            start_at=start,
            end_at=start + SLOT_LENGTH,
            status="booked",
            created_by_sub=created_by_sub,
        )
        .returning(Appointment)
    )
    return result.scalar_one()


async def get_booked(
    session: AsyncSession, doctor_id: uuid.UUID, start_at: datetime
) -> Appointment | None:
    result = await session.execute(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.start_at == start_at.astimezone(UTC),
            Appointment.status == "booked",
        )
    )
    return result.scalar_one_or_none()


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint or index a database error refers to, if the driver reports it."""
    orig = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None


def is_slot_conflict(exc: IntegrityError) -> bool:
    """True only for the double-booking index. A foreign key or CHECK failure is not a conflict."""
    name = violated_constraint(exc)
    if name is not None:
        return name == SLOT_INDEX
    return SLOT_INDEX in str(exc.orig)
