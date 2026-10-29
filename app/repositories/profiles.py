import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Doctor, Patient


async def get_patient_by_sub(session: AsyncSession, sub: str) -> Patient | None:
    result = await session.execute(select(Patient).where(Patient.keycloak_sub == sub))
    return result.scalar_one_or_none()


async def get_doctor_by_sub(session: AsyncSession, sub: str) -> Doctor | None:
    result = await session.execute(select(Doctor).where(Doctor.keycloak_sub == sub))
    return result.scalar_one_or_none()


async def insert_patient_if_absent(
    session: AsyncSession, sub: str, name: str, email: str | None
) -> bool:
    """Idempotent: two simultaneous first calls cannot fail. True if this call created the row."""
    stmt = (
        pg_insert(Patient)
        .values(keycloak_sub=sub, name=name, email=email)
        .on_conflict_do_nothing(index_elements=[Patient.keycloak_sub])
        .returning(Patient.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_patient(session: AsyncSession, patient_id: uuid.UUID) -> Patient | None:
    result = await session.execute(select(Patient).where(Patient.id == patient_id))
    return result.scalar_one_or_none()
