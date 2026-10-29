"""Only the double-booking index counts as a slot conflict (plan section 9)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.repositories.appointments import is_slot_conflict
from tests.integration.factories import START, make_appointment, make_doctor, make_patient


async def test_a_duplicate_booking_is_a_slot_conflict(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    await make_appointment(conn, doctor, patient)
    with pytest.raises(IntegrityError) as caught:
        async with conn.begin_nested():
            await make_appointment(conn, doctor, await make_patient(conn))
    assert is_slot_conflict(caught.value)


async def test_a_foreign_key_failure_is_not_a_slot_conflict(conn: AsyncConnection) -> None:
    doctor = await make_doctor(conn)
    with pytest.raises(IntegrityError) as caught:
        async with conn.begin_nested():
            await make_appointment(conn, doctor, uuid.uuid4())  # no such patient
    assert not is_slot_conflict(caught.value)


async def test_a_check_failure_is_not_a_slot_conflict(conn: AsyncConnection) -> None:
    doctor, patient = await make_doctor(conn), await make_patient(conn)
    misaligned = datetime(2030, 1, 7, 6, 15, tzinfo=UTC)
    with pytest.raises(IntegrityError) as caught:
        async with conn.begin_nested():
            await make_appointment(conn, doctor, patient, misaligned)
    assert not is_slot_conflict(caught.value)
    assert misaligned != START
