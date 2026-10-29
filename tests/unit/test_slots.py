from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.slots import (
    SLOT_LENGTH,
    BlockedInterval,
    ScheduleWindow,
    Slot,
    SlotRules,
    generate_slots,
    is_aligned,
)
from tests.unit.slot_helpers import (
    EVERY_DAY,
    MONDAY,
    MONDAY_HOURS,
    NOW,
    RULES,
    at,
    blocked,
    local_times,
    window,
)


def gen(
    windows: Sequence[ScheduleWindow] = MONDAY_HOURS,
    day: date = MONDAY,
    exceptions: Sequence[BlockedInterval] = (),
    booked: Collection[datetime] = (),
    now: datetime = NOW,
    rules: SlotRules = RULES,
) -> list[Slot]:
    return generate_slots(windows, day, exceptions, booked, now, rules)


# --- working windows --------------------------------------------------------


def test_normal_day_with_split_shift() -> None:
    slots = gen()
    times = local_times(slots)
    assert len(slots) == 15  # 9 morning (08:00-12:30) + 6 afternoon (14:00-17:00)
    assert times[0] == "08:00"
    assert times[-1] == "16:30"
    assert "12:30" not in times  # the gap between shifts has no slots
    assert "13:30" not in times
    assert all(slot.end_at - slot.start_at == SLOT_LENGTH for slot in slots)
    assert slots == sorted(slots, key=lambda slot: slot.start_at)


def test_no_hours_that_weekday() -> None:
    assert gen(windows=[window(1, "08:00", "12:30")]) == []  # hours exist only on Tuesday
    assert gen(windows=[]) == []


def test_last_slot_must_fully_fit() -> None:
    times = local_times(gen(windows=[window(0, "08:00", "12:45")]))
    assert times[-1] == "12:00"  # 12:30-13:00 would overrun the window
    assert len(times) == 9


def test_window_shorter_than_a_slot_yields_nothing() -> None:
    assert gen(windows=[window(0, "08:00", "08:20")]) == []


def test_unaligned_window_start_is_rounded_up() -> None:
    assert local_times(gen(windows=[window(0, "08:15", "10:00")])) == ["08:30", "09:00", "09:30"]


def test_every_generated_slot_is_aligned() -> None:
    assert all(is_aligned(slot.start_at) for slot in gen(windows=[window(0, "08:07", "12:30")]))


def test_is_aligned() -> None:
    assert is_aligned(at(MONDAY, "09:00"))
    assert is_aligned(at(MONDAY, "09:30"))
    assert not is_aligned(at(MONDAY, "09:10"))
    assert not is_aligned(at(MONDAY, "09:00") + timedelta(seconds=1))


# --- exceptions -------------------------------------------------------------


@pytest.mark.parametrize("kind", ["leave", "closure", "unavailable"])
def test_each_exception_type_blocks(kind: str) -> None:
    times = local_times(gen(exceptions=[blocked(MONDAY, "09:00", "10:00", kind)]))
    assert len(times) == 13
    assert "09:00" not in times
    assert "09:30" not in times


def test_exception_outside_working_hours_adds_no_hours() -> None:
    assert gen(exceptions=[blocked(MONDAY, "12:30", "14:00")]) == gen()


def test_partial_overlap_blocks_both_touched_slots() -> None:
    times = local_times(gen(exceptions=[blocked(MONDAY, "09:10", "09:40")]))
    assert "09:00" not in times
    assert "09:30" not in times
    assert "08:30" in times
    assert "10:00" in times


def test_exception_not_aligned_to_slot_boundaries() -> None:
    times = local_times(gen(exceptions=[blocked(MONDAY, "08:10", "08:20")]))
    assert "08:00" not in times
    assert "08:30" in times


def test_exception_ending_exactly_at_slot_start_does_not_block() -> None:
    assert "09:00" in local_times(gen(exceptions=[blocked(MONDAY, "08:00", "09:00")]))


def test_exception_starting_exactly_at_slot_end_does_not_block() -> None:
    assert "09:00" in local_times(gen(exceptions=[blocked(MONDAY, "09:30", "10:30")]))


def test_exception_spanning_midnight() -> None:
    previous_evening = at(MONDAY - timedelta(days=1), "22:00")
    spanning = BlockedInterval(previous_evening, at(MONDAY, "09:00"), "closure")
    times = local_times(gen(exceptions=[spanning]))
    assert times[0] == "09:00"
    assert len(times) == 13  # 08:00 and 08:30 are blocked


def test_exception_across_split_shift() -> None:
    times = local_times(gen(exceptions=[blocked(MONDAY, "12:00", "14:30")]))
    assert "11:30" in times
    assert "12:00" not in times
    assert "14:00" not in times
    assert "14:30" in times


# --- bookings, lead time, past, horizon -------------------------------------


def test_booked_slot_is_removed() -> None:
    times = local_times(gen(booked=[at(MONDAY, "09:00")]))
    assert len(times) == 14
    assert "09:00" not in times


def test_booked_matches_by_instant_not_by_offset() -> None:
    booked = [at(MONDAY, "09:00").astimezone(ZoneInfo("America/New_York"))]
    assert "09:00" not in local_times(gen(booked=booked))


@pytest.mark.parametrize(
    ("now_hhmm", "first_slot"),
    [("06:00", "08:00"), ("07:00", "08:00"), ("07:01", "08:30")],
)
def test_lead_time_boundary(now_hhmm: str, first_slot: str) -> None:
    # Exactly 60 minutes ahead is accepted; 59 is not.
    assert local_times(gen(now=at(MONDAY, now_hhmm)))[0] == first_slot


def test_slots_earlier_today_are_removed() -> None:
    times = local_times(gen(now=at(MONDAY, "10:10")))
    assert times[0] == "11:30"  # 11:10 is the earliest allowed; slots are on :00/:30
    assert len(times) == 8


def test_past_date_is_empty() -> None:
    assert gen(now=at(MONDAY + timedelta(days=1), "09:00")) == []


def test_horizon_day_90_has_slots_and_day_91_does_not() -> None:
    day_90 = date(2030, 4, 7)  # NOW is 2030-01-07 local
    assert (day_90 - date(2030, 1, 7)).days == 90
    assert len(gen(windows=EVERY_DAY, day=day_90)) == 9
    assert gen(windows=EVERY_DAY, day=day_90 + timedelta(days=1)) == []


# --- time zones -------------------------------------------------------------


def test_window_after_local_midnight_has_the_previous_utc_date() -> None:
    windows = [window(0, "00:00", "01:00")]
    slots = gen(windows=windows)
    assert len(slots) == 2
    assert slots[0].start_at.date() == MONDAY - timedelta(days=1)  # 21:00 UTC the day before
    assert gen(windows=windows, day=MONDAY - timedelta(days=1)) == []  # not a Sunday slot


NEW_YORK = ZoneInfo("America/New_York")
NY_RULES = SlotRules(timezone=NEW_YORK)


def test_spring_forward_day_uses_the_new_offset() -> None:
    spring = date(2030, 3, 10)  # US clocks go forward at 02:00
    before = date(2030, 3, 9)
    windows = [
        window(spring.weekday(), "08:00", "10:00"),
        window(before.weekday(), "08:00", "10:00"),
    ]
    now = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
    on_spring = gen(windows=windows, day=spring, now=now, rules=NY_RULES)
    on_before = gen(windows=windows, day=before, now=now, rules=NY_RULES)
    assert len(on_spring) == len(on_before) == 4
    assert on_before[0].start_at == datetime(2030, 3, 9, 13, 0, tzinfo=UTC)  # 08:00 EST
    assert on_spring[0].start_at == datetime(2030, 3, 10, 12, 0, tzinfo=UTC)  # 08:00 EDT


def test_window_spanning_spring_forward_loses_an_hour() -> None:
    spring = date(2030, 3, 10)
    slots = gen(
        windows=[window(spring.weekday(), "00:00", "04:00")],
        day=spring,
        now=datetime(2030, 3, 1, 12, 0, tzinfo=UTC),
        rules=NY_RULES,
    )
    assert len(slots) == 6  # 3 elapsed hours, not 4


def test_window_spanning_fall_back_gains_an_hour() -> None:
    fall = date(2030, 11, 3)
    slots = gen(
        windows=[window(fall.weekday(), "00:00", "04:00")],
        day=fall,
        now=datetime(2030, 10, 25, 12, 0, tzinfo=UTC),
        rules=NY_RULES,
    )
    assert len(slots) == 10  # 5 elapsed hours, not 4
