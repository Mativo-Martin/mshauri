from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.services.slots import BlockedInterval, ScheduleWindow, Slot, SlotRules

NAIROBI = ZoneInfo("Africa/Nairobi")
RULES = SlotRules(timezone=NAIROBI)

MONDAY = date(2030, 1, 14)
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)  # a week earlier; 11:00 in Nairobi


def at(day: date, hhmm: str, tz: ZoneInfo = NAIROBI) -> datetime:
    """Clinic-local wall time as an aware UTC datetime."""
    return datetime.combine(day, time.fromisoformat(hhmm), tzinfo=tz).astimezone(UTC)


def window(weekday: int, start: str, end: str) -> ScheduleWindow:
    return ScheduleWindow(weekday, time.fromisoformat(start), time.fromisoformat(end))


def blocked(day: date, start: str, end: str, kind: str = "leave") -> BlockedInterval:
    return BlockedInterval(at(day, start), at(day, end), kind)


def local_times(slots: list[Slot], tz: ZoneInfo = NAIROBI) -> list[str]:
    return [slot.start_at.astimezone(tz).strftime("%H:%M") for slot in slots]


MONDAY_HOURS = [window(0, "08:00", "12:30"), window(0, "14:00", "17:00")]
EVERY_DAY = [window(weekday, "08:00", "12:30") for weekday in range(7)]
