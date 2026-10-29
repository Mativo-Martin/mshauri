import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, func, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Doctor, Patient

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


async def get_for_update(session: AsyncSession, appointment_id: uuid.UUID) -> Appointment | None:
    """Load and lock the row until the transaction ends. Concurrent changes queue behind it."""
    result = await session.execute(
        select(Appointment)
        .where(Appointment.id == appointment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def mark_cancelled(
    session: AsyncSession,
    appointment_id: uuid.UUID,
    reason: str,
    cancelled_at: datetime,
    cancelled_by_sub: str,
) -> Appointment:
    result = await session.execute(
        update(Appointment)
        .where(Appointment.id == appointment_id)
        .values(
            status="cancelled",
            cancel_reason=reason,
            cancelled_at=cancelled_at,
            cancelled_by_sub=cancelled_by_sub,
            updated_at=func.now(),
        )
        .returning(Appointment)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


# PostgreSQL "deadlock_detected". Two appointments swapping slots can hit it (plan D13).
DEADLOCK_SQLSTATE = "40P01"


def is_deadlock(exc: DBAPIError) -> bool:
    """True when the driver reports a deadlock, whether SQLAlchemy or asyncpg holds the code."""
    orig = exc.orig
    for candidate in (orig, getattr(orig, "__cause__", None)):
        for attribute in ("sqlstate", "pgcode"):
            if getattr(candidate, attribute, None) == DEADLOCK_SQLSTATE:
                return True
    return False


async def move_appointment(
    session: AsyncSession, appointment_id: uuid.UUID, new_start_at: datetime
) -> Appointment:
    """Move the same row to a new slot. The unique index decides whether it is free."""
    start = new_start_at.astimezone(UTC)
    result = await session.execute(
        update(Appointment)
        .where(Appointment.id == appointment_id)
        .values(start_at=start, end_at=start + SLOT_LENGTH, updated_at=func.now())
        .returning(Appointment)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


AppointmentRow = tuple[Appointment, str, str]  # appointment, doctor name, patient name


async def get_by_id(session: AsyncSession, appointment_id: uuid.UUID) -> Appointment | None:
    """Plain read, no lock."""
    result = await session.execute(select(Appointment).where(Appointment.id == appointment_id))
    return result.scalar_one_or_none()


async def list_with_names(
    session: AsyncSession,
    *,
    statuses: Sequence[str],
    doctor_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    start_from: datetime | None = None,
    start_to: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[AppointmentRow], int]:
    """One page ordered by (start_at, id), plus the total. `start_to` is exclusive."""
    conditions: list[ColumnElement[bool]] = [Appointment.status.in_(statuses)]
    if doctor_id is not None:
        conditions.append(Appointment.doctor_id == doctor_id)
    if patient_id is not None:
        conditions.append(Appointment.patient_id == patient_id)
    if start_from is not None:
        conditions.append(Appointment.start_at >= start_from.astimezone(UTC))
    if start_to is not None:
        conditions.append(Appointment.start_at < start_to.astimezone(UTC))

    total = (
        await session.execute(select(func.count()).select_from(Appointment).where(*conditions))
    ).scalar_one()
    result = await session.execute(
        select(Appointment, Doctor.name, Patient.name)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(*conditions)
        .order_by(Appointment.start_at, Appointment.id)
        .limit(limit)
        .offset(offset)
    )
    return [(a, doctor_name, patient_name) for a, doctor_name, patient_name in result.all()], total
