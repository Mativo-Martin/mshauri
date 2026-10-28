import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults() -> None:
    settings = Settings()
    assert settings.clinic_timezone == "Africa/Nairobi"
    assert settings.slot_minutes == 30
    assert settings.min_lead_time_minutes == 60
    assert settings.max_booking_horizon_days == 90


def test_slot_minutes_other_than_30_fails_startup() -> None:
    with pytest.raises(ValidationError, match="SLOT_MINUTES must be 30"):
        Settings(slot_minutes=45)


def test_unknown_timezone_fails_startup() -> None:
    with pytest.raises(ValidationError, match="unknown time zone"):
        Settings(clinic_timezone="Mars/Olympus")


def test_negative_lead_time_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(min_lead_time_minutes=-1)


def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(max_booking_horizon_days=0)
