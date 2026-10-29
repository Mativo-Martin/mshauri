import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.engine import create_session_factory
from app.db.uow import UnitOfWork
from app.models import Doctor
from tests.integration.helpers import count_rows


async def test_commit_persists(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    async with UnitOfWork(factory) as uow:
        uow.session.add(Doctor(name="Dr A", external_ref="UOW-1"))
        await uow.commit()
    assert await count_rows(fresh_db, "doctors") == 1


async def test_exception_rolls_back(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    with pytest.raises(RuntimeError, match="boom"):
        async with UnitOfWork(factory) as uow:
            uow.session.add(Doctor(name="Dr A", external_ref="UOW-2"))
            await uow.session.flush()
            raise RuntimeError("boom")
    assert await count_rows(fresh_db, "doctors") == 0


async def test_leaving_without_commit_rolls_back(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    async with UnitOfWork(factory) as uow:
        uow.session.add(Doctor(name="Dr A", external_ref="UOW-3"))
        await uow.session.flush()
    assert await count_rows(fresh_db, "doctors") == 0


async def test_explicit_rollback(fresh_db: AsyncEngine) -> None:
    factory = create_session_factory(fresh_db)
    async with UnitOfWork(factory) as uow:
        uow.session.add(Doctor(name="Dr A", external_ref="UOW-4"))
        await uow.session.flush()
        await uow.rollback()
        await uow.commit()
    assert await count_rows(fresh_db, "doctors") == 0


async def test_session_unavailable_outside_block(fresh_db: AsyncEngine) -> None:
    uow = UnitOfWork(create_session_factory(fresh_db))
    with pytest.raises(RuntimeError, match="outside"):
        _ = uow.session
