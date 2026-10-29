import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, Doctor, DoctorSchedule, ScheduleException
from app.services.slots import BlockedInterval, ScheduleWindow


async def list_active_doctors(
    session: AsyncSession, specialty: str | None, limit: int, offset: int
) -> tuple[list[Doctor], int]:
    query = select(Doctor).where(Doctor.is_active.is_(True))
    if specialty:
        query = query.where(func.lower(Doctor.specialty) == specialty.lower())
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Doctor.name, Doctor.id).limit(limit).offset(offset))
    return list(rows.scalars().all()), int(total)


async def get_active_doctor(session: AsyncSession, doctor_id: uuid.UUID) -> Doctor | None:
    result = await session.execute(
        select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_windows(
    session: AsyncSession, doctor_id: uuid.UUID, weekday: int
) -> list[ScheduleWindow]:
    result = await session.execute(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.weekday == weekday
        )
    )
    return [
        ScheduleWindow(row.weekday, row.start_time, row.end_time) for row in result.scalars().all()
    ]


async def get_blocked_intervals(
    session: AsyncSession, doctor_id: uuid.UUID, range_start: datetime, range_end: datetime
) -> list[BlockedInterval]:
    result = await session.execute(
        select(ScheduleException).where(
            ScheduleException.doctor_id == doctor_id,
            ScheduleException.start_timestamp < range_end,
            ScheduleException.end_timestamp > range_start,
        )
    )
    return [
        BlockedInterval(row.start_timestamp, row.end_timestamp, row.type)
        for row in result.scalars().all()
    ]


async def get_booked_starts(
    session: AsyncSession, doctor_id: uuid.UUID, range_start: datetime, range_end: datetime
) -> list[datetime]:
    result = await session.execute(
        select(Appointment.start_at).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == "booked",
            Appointment.start_at >= range_start,
            Appointment.start_at < range_end,
        )
    )
    return list(result.scalars().all())
