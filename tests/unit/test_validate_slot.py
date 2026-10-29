from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.slots import (
    SLOT_LENGTH,
    BlockedInterval,
    ScheduleWindow,
    generate_slots,
    validate_slot,
)
from tests.unit.slot_helpers import (
    EVERY_DAY,
    MONDAY,
    MONDAY_HOURS,
    NOW,
    RULES,
    at,
    blocked,
    window,
)

GOOD = at(MONDAY, "09:00")


def validate(
    start_at: datetime,
    *,
    active: bool = True,
    windows: Sequence[ScheduleWindow] = MONDAY_HOURS,
    exceptions: Sequence[BlockedInterval] = (),
    now: datetime = NOW,
) -> None:
    validate_slot(
        doctor_active=active,
        windows=windows,
        exceptions=exceptions,
        start_at=start_at,
        now=now,
        rules=RULES,
    )


def rejected(
    start_at: datetime,
    *,
    active: bool = True,
    windows: Sequence[ScheduleWindow] = MONDAY_HOURS,
    exceptions: Sequence[BlockedInterval] = (),
    now: datetime = NOW,
) -> AppError:
    with pytest.raises(AppError) as exc:
        validate(start_at, active=active, windows=windows, exceptions=exceptions, now=now)
    return exc.value


def test_valid_slot_passes() -> None:
    validate(GOOD)


# --- one test per rule ------------------------------------------------------


def test_naive_datetime() -> None:
    error = rejected(datetime(2030, 1, 14, 9, 0))
    assert error.code == ErrorCode.NAIVE_DATETIME
    assert error.status == 422


def test_inactive_doctor_is_a_409() -> None:
    error = rejected(GOOD, active=False)
    assert error.code == ErrorCode.DOCTOR_UNAVAILABLE
    assert error.status == 409


@pytest.mark.parametrize("offset", [timedelta(minutes=10), timedelta(seconds=30)])
def test_misaligned(offset: timedelta) -> None:
    assert rejected(GOOD + offset).code == ErrorCode.SLOT_MISALIGNED


def test_slot_in_the_past() -> None:
    assert rejected(datetime(2030, 1, 6, 6, 0, tzinfo=UTC)).code == ErrorCode.SLOT_IN_PAST


def test_slot_starting_exactly_now_is_in_the_past() -> None:
    assert rejected(GOOD, now=GOOD).code == ErrorCode.SLOT_IN_PAST


def test_lead_time_exactly_60_minutes_is_accepted() -> None:
    validate(at(MONDAY, "09:00"), now=at(MONDAY, "08:00"))


def test_lead_time_59_minutes_is_rejected() -> None:
    now = at(MONDAY, "08:01")
    assert rejected(at(MONDAY, "09:00"), now=now).code == ErrorCode.SLOT_TOO_SOON


def test_thirty_minutes_ahead_is_too_soon() -> None:
    assert rejected(at(MONDAY, "08:30"), now=at(MONDAY, "08:00")).code == ErrorCode.SLOT_TOO_SOON


def test_horizon_day_90_accepted() -> None:
    validate(at(date(2030, 4, 7), "09:00"), windows=EVERY_DAY)


def test_horizon_day_91_rejected() -> None:
    error = rejected(at(date(2030, 4, 8), "09:00"), windows=EVERY_DAY)
    assert error.code == ErrorCode.BEYOND_BOOKING_HORIZON


@pytest.mark.parametrize("hhmm", ["07:30", "12:30", "13:00", "13:30", "17:00", "20:00"])
def test_outside_working_hours(hhmm: str) -> None:
    error = rejected(at(MONDAY, hhmm))
    assert error.code == ErrorCode.OUTSIDE_WORKING_HOURS
    assert error.status == 422


@pytest.mark.parametrize("hhmm", ["08:00", "12:00", "14:00", "16:30"])
def test_inside_working_hours(hhmm: str) -> None:
    validate(at(MONDAY, hhmm))


def test_slot_must_fully_fit_the_window() -> None:
    windows = [window(0, "08:00", "12:45")]
    assert rejected(at(MONDAY, "12:30"), windows=windows).code == ErrorCode.OUTSIDE_WORKING_HOURS
    validate(at(MONDAY, "12:00"), windows=windows)


def test_weekday_without_hours() -> None:
    tuesday = MONDAY + timedelta(days=1)
    assert rejected(at(tuesday, "09:00")).code == ErrorCode.OUTSIDE_WORKING_HOURS


def test_slot_after_local_midnight_uses_the_local_weekday() -> None:
    # 00:00 Monday in Nairobi is 21:00 UTC on Sunday; the Monday window must apply.
    validate(at(MONDAY, "00:00"), windows=[window(0, "00:00", "01:00")])


@pytest.mark.parametrize("kind", ["leave", "closure", "unavailable"])
def test_slot_inside_an_exception_is_422_not_409(kind: str) -> None:
    error = rejected(GOOD, exceptions=[blocked(MONDAY, "09:00", "10:00", kind)])
    assert error.code == ErrorCode.OUTSIDE_WORKING_HOURS
    assert error.status == 422
    assert kind in error.detail  # the message names the reason


def test_slot_adjacent_to_an_exception_is_accepted() -> None:
    exceptions = [blocked(MONDAY, "09:00", "10:00")]
    validate(at(MONDAY, "08:30"), exceptions=exceptions)
    validate(at(MONDAY, "10:00"), exceptions=exceptions)


# --- order: first failure wins ---------------------------------------------


def test_order_naive_before_inactive() -> None:
    assert rejected(datetime(2030, 1, 14, 9, 0), active=False).code == ErrorCode.NAIVE_DATETIME


def test_order_inactive_before_misaligned() -> None:
    error = rejected(GOOD + timedelta(minutes=10), active=False)
    assert error.code == ErrorCode.DOCTOR_UNAVAILABLE


def test_order_misaligned_before_past() -> None:
    error = rejected(datetime(2030, 1, 6, 6, 10, tzinfo=UTC))
    assert error.code == ErrorCode.SLOT_MISALIGNED


def test_order_past_before_too_soon() -> None:
    assert rejected(datetime(2030, 1, 6, 6, 0, tzinfo=UTC)).code == ErrorCode.SLOT_IN_PAST


def test_order_too_soon_before_outside_hours() -> None:
    error = rejected(at(MONDAY, "06:30"), now=at(MONDAY, "06:00"))
    assert error.code == ErrorCode.SLOT_TOO_SOON


def test_order_horizon_before_outside_hours() -> None:
    error = rejected(at(date(2030, 4, 8), "07:00"))  # day 91 and before opening time
    assert error.code == ErrorCode.BEYOND_BOOKING_HORIZON


# --- availability and booking never disagree (plan D7) ----------------------


def test_validate_agrees_with_generate_slots() -> None:
    windows = [window(0, "08:15", "12:30"), window(0, "14:00", "17:00")]
    exceptions = [blocked(MONDAY, "09:10", "09:40"), blocked(MONDAY, "15:00", "15:30", "closure")]
    generated = {s.start_at for s in generate_slots(windows, MONDAY, exceptions, (), NOW, RULES)}
    assert generated  # sanity: the scenario is not vacuous

    midnight = at(MONDAY, "00:00")
    for step in range(48):
        candidate = midnight + step * SLOT_LENGTH
        try:
            validate(candidate, windows=windows, exceptions=exceptions)
            accepted = True
        except AppError:
            accepted = False
        assert accepted == (candidate in generated), candidate
