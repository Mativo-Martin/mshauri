from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import Doctor, DoctorSchedule, Patient, ScheduleException
from tests.integration.factories import START, make_appointment, make_doctor, make_patient


async def assert_violates(
    conn: AsyncConnection, constraint: str, call: Callable[[], Awaitable[object]]
) -> None:
    """Run `call` in a savepoint; it must fail naming `constraint`. The transaction stays usable."""
    with pytest.raises(IntegrityError) as exc:
        async with conn.begin_nested():
            await call()
    assert constraint in str(exc.value)


# --- double-booking guard ---------------------------------------------------


async def test_second_booked_row_for_same_slot_is_rejected(conn: AsyncConnection) -> None:
    doctor, patient1, patient2 = (
        await make_doctor(conn),
        await make_patient(conn),
        await make_patient(conn),
    )
    await make_appointment(conn, doctor, patient1)
    await assert_violates(
        conn,
        "uq_appointments_doctor_start_booked",
        lambda: make_appointment(conn, doctor, patient2),
    )


async def test_cancelled_row_does_not_block_new_booking(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    cancel = {
        "status": "cancelled",
        "cancel_reason": "patient request",
        "cancelled_at": datetime.now(UTC),
        "cancelled_by_sub": "test-sub",
    }
    await make_appointment(conn, doctor, patient, **cancel)  # type: ignore[arg-type]
    await make_appointment(conn, doctor, patient, **cancel)  # type: ignore[arg-type]
    await make_appointment(conn, doctor, patient)  # booked into the freed slot


async def test_same_time_for_different_doctors_is_allowed(conn: AsyncConnection) -> None:
    doctor1, doctor2, patient = (
        await make_doctor(conn),
        await make_doctor(conn),
        await make_patient(conn),
    )
    await make_appointment(conn, doctor1, patient)
    await make_appointment(conn, doctor2, patient)


# --- CHECK constraints on appointments --------------------------------------


async def test_wrong_duration_rejected(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await assert_violates(
        conn,
        "ck_appointments_duration",
        lambda: make_appointment(conn, doctor, patient, end_at=START + timedelta(minutes=60)),
    )


async def test_misaligned_start_rejected(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await assert_violates(
        conn,
        "ck_appointments_aligned",
        lambda: make_appointment(conn, doctor, patient, START + timedelta(minutes=10)),
    )


async def test_cancelled_without_reason_rejected(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await assert_violates(
        conn,
        "ck_appointments_cancel_fields",
        lambda: make_appointment(
            conn,
            doctor,
            patient,
            status="cancelled",
            cancelled_at=datetime.now(UTC),
            cancelled_by_sub="test-sub",
        ),
    )


async def test_cancelled_with_blank_reason_rejected(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await assert_violates(
        conn,
        "ck_appointments_cancel_fields",
        lambda: make_appointment(
            conn,
            doctor,
            patient,
            status="cancelled",
            cancel_reason="   ",
            cancelled_at=datetime.now(UTC),
            cancelled_by_sub="test-sub",
        ),
    )


async def test_booked_with_cancel_fields_rejected(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await assert_violates(
        conn,
        "ck_appointments_cancel_fields",
        lambda: make_appointment(conn, doctor, patient, cancel_reason="should be empty"),
    )


# --- foreign keys restrict deletes ------------------------------------------


async def test_cannot_delete_doctor_with_appointments(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await make_appointment(conn, doctor, patient)
    await assert_violates(
        conn,
        "fk_appointments_doctor_id_doctors",
        lambda: conn.execute(delete(Doctor).where(Doctor.id == doctor)),
    )


async def test_cannot_delete_patient_with_appointments(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await make_appointment(conn, doctor, patient)
    await assert_violates(
        conn,
        "fk_appointments_patient_id_patients",
        lambda: conn.execute(delete(Patient).where(Patient.id == patient)),
    )


# --- schedules, exceptions, doctors -----------------------------------------


async def test_schedule_weekday_out_of_range_rejected(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    await assert_violates(
        conn,
        "ck_doctor_schedules_weekday_range",
        lambda: conn.execute(
            insert(DoctorSchedule).values(
                doctor_id=doctor, weekday=7, start_time=time(8, 0), end_time=time(12, 30)
            )
        ),
    )


async def test_schedule_end_before_start_rejected(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    await assert_violates(
        conn,
        "ck_doctor_schedules_end_after_start",
        lambda: conn.execute(
            insert(DoctorSchedule).values(
                doctor_id=doctor, weekday=0, start_time=time(12, 30), end_time=time(8, 0)
            )
        ),
    )


async def test_exception_end_before_start_rejected(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    await assert_violates(
        conn,
        "ck_schedule_exceptions_end_after_start",
        lambda: conn.execute(
            insert(ScheduleException).values(
                doctor_id=doctor,
                start_timestamp=START,
                end_timestamp=START - timedelta(hours=1),
                type="leave",
            )
        ),
    )


async def test_exception_unknown_type_rejected(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    await assert_violates(
        conn,
        "ck_schedule_exceptions_type",
        lambda: conn.execute(
            insert(ScheduleException).values(
                doctor_id=doctor,
                start_timestamp=START,
                end_timestamp=START + timedelta(hours=1),
                type="sick",
            )
        ),
    )


async def test_exception_types_accepted(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    for kind in ("leave", "closure", "unavailable"):
        await conn.execute(
            insert(ScheduleException).values(
                doctor_id=doctor,
                start_timestamp=START,
                end_timestamp=START + timedelta(hours=1),
                type=kind,
            )
        )


async def test_duplicate_external_ref_rejected(conn: AsyncConnection) -> None:
    await make_doctor(conn, external_ref="LEGACY-1")
    await assert_violates(
        conn, "uq_doctors_external_ref", lambda: make_doctor(conn, external_ref="LEGACY-1")
    )
