"""Open slots for one doctor on one clinic-local date (plan section 7)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.repositories import doctors as repo
from app.services.slots import Slot, SlotRules, generate_slots, within_horizon


def local_day_bounds(day: date, rules: SlotRules) -> tuple[datetime, datetime]:
    """The UTC instants where this clinic-local calendar day starts and ends."""
    start = datetime.combine(day, time.min, tzinfo=rules.timezone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=rules.timezone).astimezone(UTC)
    return start, end


async def get_availability(
    session: AsyncSession, doctor_id: uuid.UUID, day: date, now: datetime, rules: SlotRules
) -> list[Slot]:
    doctor = await repo.get_doctor(session, doctor_id)
    if doctor is None:
        raise AppError(ErrorCode.DOCTOR_NOT_FOUND)
    if not doctor.is_active:
        raise AppError(ErrorCode.DOCTOR_UNAVAILABLE)
    if not within_horizon(day, now, rules):
        raise AppError(ErrorCode.BEYOND_BOOKING_HORIZON)

    range_start, range_end = local_day_bounds(day, rules)
    windows = await repo.get_windows(session, doctor_id, day.weekday())
    blocked = await repo.get_blocked_intervals(session, doctor_id, range_start, range_end)
    booked = await repo.get_booked_starts(session, doctor_id, range_start, range_end)
    return generate_slots(windows, day, blocked, booked, now, rules)
