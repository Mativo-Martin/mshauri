"""One slot check for book and reschedule (plan D6), so the two paths cannot drift."""

import uuid
from datetime import UTC, datetime

from app.db.uow import UnitOfWork
from app.repositories import doctors as doctor_repo
from app.services.availability import local_day_bounds
from app.services.slots import SlotRules, validate_slot


async def check_slot(
    uow: UnitOfWork,
    *,
    doctor_id: uuid.UUID,
    doctor_active: bool,
    start_at: datetime,
    now: datetime,
    rules: SlotRules,
) -> None:
    """Load the doctor's windows and exceptions for the slot's local day, then validate_slot."""
    start = start_at.astimezone(UTC)
    local_day = start.astimezone(rules.timezone).date()
    day_start, day_end = local_day_bounds(local_day, rules)
    session = uow.session
    windows = await doctor_repo.get_windows(session, doctor_id, local_day.weekday())
    blocked = await doctor_repo.get_blocked_intervals(session, doctor_id, day_start, day_end)
    validate_slot(
        doctor_active=doctor_active,
        windows=windows,
        exceptions=blocked,
        start_at=start,
        now=now,
        rules=rules,
    )
