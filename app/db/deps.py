from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.db.engine import get_session_factory
from app.db.uow import UnitOfWork


async def get_uow(
    factory: Annotated[async_sessionmaker[AsyncSession] | None, Depends(get_session_factory)],
) -> AsyncIterator[UnitOfWork]:
    """A unit of work per request. Reads never commit, so the UoW rolls back on exit."""
    if factory is None:
        raise AppError(ErrorCode.INTERNAL_ERROR)
    async with UnitOfWork(factory) as uow:
        yield uow
