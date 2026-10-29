from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    # pool_pre_ping drops dead connections; the connect timeout keeps /ready from hanging.
    return create_async_engine(url, pool_pre_ping=True, connect_args={"timeout": 5})


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def get_engine(request: Request) -> AsyncEngine | None:
    """FastAPI dependency. None when no DATABASE_URL is configured."""
    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    return engine


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession] | None:
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "session_factory", None
    )
    return factory
