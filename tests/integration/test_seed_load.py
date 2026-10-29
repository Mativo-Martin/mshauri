from dataclasses import replace

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.engine import create_session_factory
from app.models import Doctor
from app.seeding.load import apply_seed
from app.seeding.parse import parse_seed, stable_id
from tests.integration.db import ROOT
from tests.integration.helpers import table_counts

SEED_DIR = ROOT / "seed"


async def test_seed_is_idempotent(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    data = parse_seed(SEED_DIR)

    first = await apply_seed(factory, data)
    before = await table_counts(fresh_db)
    second = await apply_seed(factory, data)

    assert first == second
    assert await table_counts(fresh_db) == before
    assert before == {
        "doctors": len(data.doctors),
        "doctor_schedules": len(data.schedules),
        "schedule_exceptions": len(data.exceptions),
    }


async def test_doctor_ids_are_deterministic(fresh_db: AsyncEngine) -> None:
    data = parse_seed(SEED_DIR)
    await apply_seed(create_session_factory(fresh_db), data)
    async with fresh_db.connect() as conn:
        rows = (await conn.execute(select(Doctor.external_ref, Doctor.id))).all()
    expected = {d.external_ref: stable_id("doctor", d.external_ref) for d in data.doctors}
    assert {row[0]: row[1] for row in rows} == expected


async def test_reseed_keeps_keycloak_link(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    data = parse_seed(SEED_DIR)
    await apply_seed(factory, data)
    async with fresh_db.begin() as conn:
        await conn.execute(
            update(Doctor).where(Doctor.external_ref == "DOC-003").values(keycloak_sub="kc-sub-1")
        )

    await apply_seed(factory, data)

    async with fresh_db.connect() as conn:
        result = await conn.execute(
            select(Doctor.keycloak_sub).where(Doctor.external_ref == "DOC-003")
        )
        assert result.scalar_one() == "kc-sub-1"


async def test_schedules_are_replaced_not_accumulated(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    data = parse_seed(SEED_DIR)
    await apply_seed(factory, data)

    await apply_seed(factory, replace(data, schedules=data.schedules[:10]))

    assert (await table_counts(fresh_db))["doctor_schedules"] == 10


async def test_seed_applies_the_keycloak_link_declared_in_the_csv(fresh_db: AsyncEngine) -> None:
    """A non-blank keycloak_sub in doctors.csv is applied; a blank one never erases a link."""
    await apply_seed(create_session_factory(fresh_db), parse_seed(SEED_DIR))
    async with fresh_db.connect() as conn:
        result = await conn.execute(
            select(Doctor.keycloak_sub).where(Doctor.external_ref == "DOC-001")
        )
    assert result.scalar_one() == "a2000000-0000-4000-8000-000000000001"
