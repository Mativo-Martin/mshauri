"""Pure CSV parsing and validation for seed data. No database access.

Errors name the file, the row number and the reason. They never echo the row's values.
"""

import csv
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

# Fixed namespace: seeded IDs are UUIDv5 values and never change between deploys.
NAMESPACE = uuid.UUID("0b1c4a52-7d0e-4c1a-9a53-3f6f5f1d2a10")
EXCEPTION_TYPES = frozenset({"leave", "closure", "unavailable"})

DOCTOR_COLUMNS = ("external_ref", "name", "specialty", "is_active", "keycloak_sub")
SCHEDULE_COLUMNS = ("doctor_ref", "weekday", "start_time", "end_time")
EXCEPTION_COLUMNS = ("doctor_ref", "type", "start_timestamp", "end_timestamp", "reason")

Row = tuple[int, dict[str, str]]


def stable_id(*parts: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "|".join(parts))


class SeedError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} problem(s) in seed data")
        self.errors = errors


@dataclass(frozen=True)
class DoctorRow:
    external_ref: str
    name: str
    specialty: str | None
    is_active: bool
    keycloak_sub: str | None


@dataclass(frozen=True)
class ScheduleRow:
    row: int
    doctor_ref: str
    weekday: int
    start: time
    end: time


@dataclass(frozen=True)
class ExceptionRow:
    doctor_ref: str
    type: str
    start: datetime
    end: datetime
    reason: str | None


@dataclass(frozen=True)
class SeedData:
    doctors: list[DoctorRow]
    schedules: list[ScheduleRow]
    exceptions: list[ExceptionRow]


def read_csv(path: Path, columns: tuple[str, ...], errors: list[str]) -> list[Row]:
    if not path.is_file():
        errors.append(f"{path.name}: file not found")
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or set(reader.fieldnames) != set(columns):
            errors.append(f"{path.name}: header must be exactly: {', '.join(columns)}")
            return []
        rows: list[Row] = []
        for number, raw in enumerate(reader, start=2):  # line 1 is the header
            if None in raw:
                errors.append(f"{path.name} row {number}: too many fields")
                continue
            rows.append((number, {key: (value or "").strip() for key, value in raw.items()}))
        return rows


def _parse_time(value: str) -> time | None:
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is None else None  # clinic-local wall time only


def _parse_aware(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None  # naive datetimes are rejected


def _parse_weekday(value: str) -> int | None:
    if value.isdigit() and 0 <= int(value) <= 6:
        return int(value)
    return None


def parse_doctors(rows: list[Row], file: str, errors: list[str]) -> list[DoctorRow]:
    seen: set[str] = set()
    parsed: list[DoctorRow] = []
    for number, row in rows:
        problems: list[str] = []
        ref = row["external_ref"]
        if not ref:
            problems.append("external_ref is required")
        elif ref in seen:
            problems.append("duplicate external_ref")
        if not row["name"]:
            problems.append("name is required")
        active = row["is_active"].lower()
        if active not in ("true", "false"):
            problems.append("is_active must be true or false")
        if problems:
            errors.extend(f"{file} row {number}: {problem}" for problem in problems)
            continue
        seen.add(ref)
        parsed.append(
            DoctorRow(
                external_ref=ref,
                name=row["name"],
                specialty=row["specialty"] or None,
                is_active=active == "true",
                keycloak_sub=row["keycloak_sub"] or None,
            )
        )
    return parsed


def parse_schedules(
    rows: list[Row], file: str, known_refs: set[str], errors: list[str]
) -> list[ScheduleRow]:
    parsed: list[ScheduleRow] = []
    for number, row in rows:
        problems: list[str] = []
        if row["doctor_ref"] not in known_refs:
            problems.append("unknown doctor_ref")
        weekday = _parse_weekday(row["weekday"])
        if weekday is None:
            problems.append("weekday must be a number from 0 (Monday) to 6 (Sunday)")
        start = _parse_time(row["start_time"])
        end = _parse_time(row["end_time"])
        if start is None:
            problems.append("start_time must be HH:MM clinic-local time")
        if end is None:
            problems.append("end_time must be HH:MM clinic-local time")
        if start is not None and end is not None and end <= start:
            problems.append("end_time must be after start_time")
        if problems or weekday is None or start is None or end is None:
            errors.extend(f"{file} row {number}: {problem}" for problem in problems)
            continue
        parsed.append(ScheduleRow(number, row["doctor_ref"], weekday, start, end))

    groups: dict[tuple[str, int], list[ScheduleRow]] = defaultdict(list)
    for item in parsed:
        groups[(item.doctor_ref, item.weekday)].append(item)
    for group in groups.values():
        group.sort(key=lambda item: item.start)
        for previous, current in zip(group, group[1:], strict=False):
            if current.start < previous.end:
                errors.append(
                    f"{file} rows {previous.row} and {current.row}: "
                    "overlapping shifts for the same doctor and weekday"
                )
    return parsed


def parse_exceptions(
    rows: list[Row], file: str, known_refs: set[str], errors: list[str]
) -> list[ExceptionRow]:
    parsed: list[ExceptionRow] = []
    for number, row in rows:
        problems: list[str] = []
        if row["doctor_ref"] not in known_refs:
            problems.append("unknown doctor_ref")
        if row["type"] not in EXCEPTION_TYPES:
            problems.append("type must be leave, closure or unavailable")
        start = _parse_aware(row["start_timestamp"])
        end = _parse_aware(row["end_timestamp"])
        if start is None:
            problems.append("start_timestamp must be ISO 8601 with a UTC offset")
        if end is None:
            problems.append("end_timestamp is required and must be ISO 8601 with a UTC offset")
        if start is not None and end is not None and end <= start:
            problems.append("end_timestamp must be after start_timestamp")
        if problems or start is None or end is None:
            errors.extend(f"{file} row {number}: {problem}" for problem in problems)
            continue
        parsed.append(
            ExceptionRow(row["doctor_ref"], row["type"], start, end, row["reason"] or None)
        )
    return parsed


def parse_seed(seed_dir: Path) -> SeedData:
    """Parse and validate all three files. Raises SeedError listing every problem found."""
    errors: list[str] = []
    doctors = parse_doctors(
        read_csv(seed_dir / "doctors.csv", DOCTOR_COLUMNS, errors), "doctors.csv", errors
    )
    refs = {doctor.external_ref for doctor in doctors}
    schedules = parse_schedules(
        read_csv(seed_dir / "schedules.csv", SCHEDULE_COLUMNS, errors),
        "schedules.csv",
        refs,
        errors,
    )
    exceptions = parse_exceptions(
        read_csv(seed_dir / "exceptions.csv", EXCEPTION_COLUMNS, errors),
        "exceptions.csv",
        refs,
        errors,
    )
    if errors:
        raise SeedError(errors)
    return SeedData(doctors, schedules, exceptions)
