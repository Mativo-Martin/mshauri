"""Apply parsed seed data to the database in one transaction. Idempotent.

- Doctors: upsert keyed by external_ref. A blank keycloak_sub never unlinks an existing one.
- Schedules: replaced per doctor (the file is the source of truth for doctors it lists).
- Exceptions: upsert only; nothing is deleted.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.uow import UnitOfWork
from app.models import Doctor, DoctorSchedule, ScheduleException
from app.seeding.parse import SeedData, stable_id


@dataclass(frozen=True)
class SeedReport:
    doctors: int
    schedules: int
    exceptions: int


async def apply_seed(
    session_factory: async_sessionmaker[AsyncSession], data: SeedData
) -> SeedReport:
    async with UnitOfWork(session_factory) as uow:
        session = uow.session

        doctor_rows: list[dict[str, Any]] = [
            {
                "id": stable_id("doctor", d.external_ref),
                "external_ref": d.external_ref,
                "name": d.name,
                "specialty": d.specialty,
                "is_active": d.is_active,
                "keycloak_sub": d.keycloak_sub,
            }
            for d in data.doctors
        ]
        if doctor_rows:
            stmt = pg_insert(Doctor).values(doctor_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Doctor.external_ref],
                set_={
                    "name": stmt.excluded["name"],
                    "specialty": stmt.excluded["specialty"],
                    "is_active": stmt.excluded["is_active"],
                    "keycloak_sub": func.coalesce(
                        stmt.excluded["keycloak_sub"], Doctor.keycloak_sub
                    ),
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)

        # An existing doctor keeps its original id, so resolve ids from the database.
        refs = [d.external_ref for d in data.doctors]
        result = await session.execute(
            select(Doctor.external_ref, Doctor.id).where(Doctor.external_ref.in_(refs))
        )
        ids: dict[str, uuid.UUID] = {str(ref): doctor_id for ref, doctor_id in result.all()}

        await session.execute(
            delete(DoctorSchedule).where(DoctorSchedule.doctor_id.in_(list(ids.values())))
        )
        schedule_rows: list[dict[str, Any]] = [
            {
                "id": stable_id(
                    "schedule", s.doctor_ref, str(s.weekday), s.start.isoformat(), s.end.isoformat()
                ),
                "doctor_id": ids[s.doctor_ref],
                "weekday": s.weekday,
                "start_time": s.start,
                "end_time": s.end,
            }
            for s in data.schedules
        ]
        if schedule_rows:
            await session.execute(pg_insert(DoctorSchedule).values(schedule_rows))

        exception_rows: list[dict[str, Any]] = [
            {
                "id": stable_id(
                    "exception", e.doctor_ref, e.type, e.start.isoformat(), e.end.isoformat()
                ),
                "doctor_id": ids[e.doctor_ref],
                "type": e.type,
                "start_timestamp": e.start,
                "end_timestamp": e.end,
                "reason": e.reason,
            }
            for e in data.exceptions
        ]
        if exception_rows:
            ex_stmt = pg_insert(ScheduleException).values(exception_rows)
            ex_stmt = ex_stmt.on_conflict_do_update(
                index_elements=[ScheduleException.id],
                set_={"reason": ex_stmt.excluded["reason"]},
            )
            await session.execute(ex_stmt)

        await uow.commit()

    return SeedReport(len(doctor_rows), len(schedule_rows), len(exception_rows))
