"""Pure slot rules (plan section 7). No database or HTTP imports.

All datetimes are timezone-aware. Working windows are clinic-local wall times: each window
is converted to UTC and then stepped in elapsed 30-minute units, so DST days stay correct.
Only slots on a :00/:30 boundary (the database CHECK's definition, measured from the epoch)
are ever produced, so availability never offers a slot that booking would reject.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import AppError, ErrorCode

SLOT_LENGTH = timedelta(minutes=30)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SlotRules:
    timezone: ZoneInfo
    min_lead_time: timedelta = timedelta(minutes=60)
    max_horizon_days: int = 90


@dataclass(frozen=True)
class ScheduleWindow:
    """One recurring working window, clinic-local. weekday: Monday = 0."""

    weekday: int
    start: time
    end: time


@dataclass(frozen=True)
class BlockedInterval:
    """A schedule exception. leave, closure and unavailable all block; none adds hours."""

    start: datetime
    end: datetime
    kind: str


@dataclass(frozen=True)
class Slot:
    start_at: datetime  # UTC
    end_at: datetime  # UTC


def is_aligned(moment: datetime) -> bool:
    return (moment - _EPOCH) % SLOT_LENGTH == timedelta(0)


def within_horizon(day: date, now: datetime, rules: SlotRules) -> bool:
    today = now.astimezone(rules.timezone).date()
    return day <= today + timedelta(days=rules.max_horizon_days)


def _require_aware(name: str, moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _local_to_utc(day: date, wall: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, wall, tzinfo=tz).astimezone(UTC)


def _ceil_to_boundary(moment: datetime) -> datetime:
    remainder = (moment - _EPOCH) % SLOT_LENGTH
    return moment if remainder == timedelta(0) else moment + (SLOT_LENGTH - remainder)


def _window_slots(windows: Sequence[ScheduleWindow], day: date, rules: SlotRules) -> list[Slot]:
    """Every aligned slot that fully fits inside a working window on this clinic-local date."""
    found: dict[datetime, Slot] = {}
    for window in windows:
        if window.weekday != day.weekday():
            continue
        current = _ceil_to_boundary(_local_to_utc(day, window.start, rules.timezone))
        end = _local_to_utc(day, window.end, rules.timezone)
        while current + SLOT_LENGTH <= end:
            found[current] = Slot(current, current + SLOT_LENGTH)
            current += SLOT_LENGTH
    return sorted(found.values(), key=lambda slot: slot.start_at)


def _blocker(slot: Slot, exceptions: Sequence[BlockedInterval]) -> BlockedInterval | None:
    """First exception overlapping the slot. Half-open: touching at an edge does not block."""
    for exception in exceptions:
        if slot.start_at < exception.end and slot.end_at > exception.start:
            return exception
    return None


def generate_slots(
    windows: Sequence[ScheduleWindow],
    day: date,
    exceptions: Sequence[BlockedInterval],
    booked_starts: Collection[datetime],
    now: datetime,
    rules: SlotRules,
) -> list[Slot]:
    """Bookable slots for one doctor on one clinic-local date, in time order."""
    _require_aware("now", now)
    if not within_horizon(day, now, rules):
        return []
    earliest = now + rules.min_lead_time
    booked = set(booked_starts)
    return [
        slot
        for slot in _window_slots(windows, day, rules)
        if slot.start_at > now
        and slot.start_at >= earliest
        and slot.start_at not in booked
        and _blocker(slot, exceptions) is None
    ]


def validate_slot(
    *,
    doctor_active: bool,
    windows: Sequence[ScheduleWindow],
    exceptions: Sequence[BlockedInterval],
    start_at: datetime,
    now: datetime,
    rules: SlotRules,
) -> None:
    """Shared by book and reschedule. Checks run in a fixed order; the first failure wins.

    "Slot already taken" is not checked here: the database constraint decides that.
    """
    _require_aware("now", now)
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise AppError(ErrorCode.NAIVE_DATETIME)
    if not doctor_active:
        raise AppError(ErrorCode.DOCTOR_UNAVAILABLE)
    if not is_aligned(start_at):
        raise AppError(ErrorCode.SLOT_MISALIGNED)
    if start_at <= now:
        raise AppError(ErrorCode.SLOT_IN_PAST)
    if start_at < now + rules.min_lead_time:
        raise AppError(ErrorCode.SLOT_TOO_SOON)

    local_day = start_at.astimezone(rules.timezone).date()
    if not within_horizon(local_day, now, rules):
        raise AppError(ErrorCode.BEYOND_BOOKING_HORIZON)

    start_utc = start_at.astimezone(UTC)
    if start_utc not in {slot.start_at for slot in _window_slots(windows, local_day, rules)}:
        raise AppError(ErrorCode.OUTSIDE_WORKING_HOURS)
    blocker = _blocker(Slot(start_utc, start_utc + SLOT_LENGTH), exceptions)
    if blocker is not None:
        raise AppError(
            ErrorCode.OUTSIDE_WORKING_HOURS,
            f"Doctor is unavailable at that time ({blocker.kind}).",
        )
