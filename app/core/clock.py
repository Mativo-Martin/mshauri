"""The one source of "now". Endpoints depend on it so tests can pin the time."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
