from pathlib import Path

import pytest

from app.seeding.parse import SeedError, parse_seed, stable_id

REAL_SEED = Path(__file__).resolve().parents[2] / "seed"

HEADERS = {
    "doctors.csv": "external_ref,name,specialty,is_active,keycloak_sub",
    "schedules.csv": "doctor_ref,weekday,start_time,end_time",
    "exceptions.csv": "doctor_ref,type,start_timestamp,end_timestamp,reason",
}


def write_seed(
    tmp_path: Path,
    doctors: tuple[str, ...] = ("D1,Dr One,GP,true,",),
    schedules: tuple[str, ...] = ("D1,0,08:00,12:30",),
    exceptions: tuple[str, ...] = (),
) -> Path:
    for name, rows in (
        ("doctors.csv", doctors),
        ("schedules.csv", schedules),
        ("exceptions.csv", exceptions),
    ):
        (tmp_path / name).write_text("\n".join([HEADERS[name], *rows]) + "\n")
    return tmp_path


def errors_for(path: Path) -> list[str]:
    with pytest.raises(SeedError) as exc:
        parse_seed(path)
    return exc.value.errors


def test_valid_data_parses(tmp_path: Path) -> None:
    data = parse_seed(
        write_seed(
            tmp_path,
            exceptions=("D1,leave,2026-11-02T00:00:00+03:00,2026-11-03T00:00:00+03:00,Leave",),
        )
    )
    assert len(data.doctors) == 1
    assert len(data.schedules) == 1
    assert len(data.exceptions) == 1


def test_committed_seed_files_are_valid() -> None:
    data = parse_seed(REAL_SEED)
    assert len(data.doctors) == 5


def test_overlapping_shifts_rejected(tmp_path: Path) -> None:
    errors = errors_for(write_seed(tmp_path, schedules=("D1,0,08:00,12:30", "D1,0,12:00,14:00")))
    assert any("overlapping" in e for e in errors)


def test_adjacent_shifts_allowed(tmp_path: Path) -> None:
    data = parse_seed(write_seed(tmp_path, schedules=("D1,0,08:00,12:30", "D1,0,12:30,14:00")))
    assert len(data.schedules) == 2


def test_same_hours_on_different_weekdays_allowed(tmp_path: Path) -> None:
    data = parse_seed(write_seed(tmp_path, schedules=("D1,0,08:00,12:30", "D1,1,08:00,12:30")))
    assert len(data.schedules) == 2


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ("D1,0,12:30,08:00", "end_time must be after start_time"),
        ("D1,0,08:00,08:00", "end_time must be after start_time"),
        ("D1,7,08:00,12:30", "weekday must be a number"),
        ("D1,monday,08:00,12:30", "weekday must be a number"),
        ("D1,0,8am,12:30", "start_time must be HH:MM"),
        ("D1,0,08:00,", "end_time must be HH:MM"),
        ("D9,0,08:00,12:30", "unknown doctor_ref"),
    ],
)
def test_bad_schedule_rows_rejected(tmp_path: Path, row: str, fragment: str) -> None:
    errors = errors_for(write_seed(tmp_path, schedules=(row,)))
    assert any(fragment in e for e in errors)
    assert all("schedules.csv row 2" in e for e in errors)  # row number is reported


def test_duplicate_external_ref_rejected(tmp_path: Path) -> None:
    errors = errors_for(write_seed(tmp_path, doctors=("D1,Dr One,GP,true,", "D1,Dr Two,GP,true,")))
    assert any("duplicate external_ref" in e for e in errors)


def test_bad_doctor_fields_rejected(tmp_path: Path) -> None:
    errors = errors_for(write_seed(tmp_path, doctors=(",,GP,maybe,",)))
    assert (
        len([e for e in errors if e.startswith("doctors.csv")]) == 3
    )  # external_ref, name, is_active


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ("D1,leave,2026-11-02T00:00:00,2026-11-03T00:00:00+03:00,x", "start_timestamp"),
        ("D1,leave,2026-11-02T00:00:00+03:00,,x", "end_timestamp is required"),
        ("D1,leave,2026-11-03T00:00:00+03:00,2026-11-02T00:00:00+03:00,x", "must be after"),
        ("D1,sick,2026-11-02T00:00:00+03:00,2026-11-03T00:00:00+03:00,x", "type must be"),
        ("D9,leave,2026-11-02T00:00:00+03:00,2026-11-03T00:00:00+03:00,x", "unknown doctor_ref"),
    ],
)
def test_bad_exception_rows_rejected(tmp_path: Path, row: str, fragment: str) -> None:
    errors = errors_for(write_seed(tmp_path, exceptions=(row,)))
    assert any(fragment in e for e in errors)


def test_wrong_header_rejected(tmp_path: Path) -> None:
    write_seed(tmp_path)
    (tmp_path / "doctors.csv").write_text("id,name\n1,Dr One\n")
    assert any("header must be exactly" in e for e in errors_for(tmp_path))


def test_missing_file_rejected(tmp_path: Path) -> None:
    write_seed(tmp_path)
    (tmp_path / "exceptions.csv").unlink()
    assert any("file not found" in e for e in errors_for(tmp_path))


def test_all_problems_reported_together(tmp_path: Path) -> None:
    errors = errors_for(
        write_seed(
            tmp_path,
            doctors=("D1,Dr One,GP,maybe,",),
            schedules=("D1,9,08:00,12:30",),
        )
    )
    assert len(errors) >= 2


def test_errors_never_echo_row_values(tmp_path: Path) -> None:
    errors = errors_for(
        write_seed(
            tmp_path,
            exceptions=(
                "D1,sick,2026-11-02T00:00:00+03:00,2026-11-03T00:00:00+03:00,SENSITIVE-REASON",
            ),
        )
    )
    assert "SENSITIVE-REASON" not in " ".join(errors)


def test_stable_id_is_deterministic_and_distinct() -> None:
    assert stable_id("doctor", "DOC-001") == stable_id("doctor", "DOC-001")
    assert stable_id("doctor", "DOC-001") != stable_id("doctor", "DOC-002")
    assert stable_id("doctor", "DOC-001") != stable_id("schedule", "DOC-001")
