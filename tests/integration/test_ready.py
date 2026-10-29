from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.engine import create_engine, get_engine
from app.main import create_app


def client_for(engine: AsyncEngine | None) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_ready_200_when_database_answers(migrated_db_url: str) -> None:
    engine = create_engine(migrated_db_url)
    try:
        async with client_for(engine) as client:
            response = await client.get("/ready")
    finally:
        await engine.dispose()
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_503_when_database_unreachable() -> None:
    engine = create_engine("postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nothing")
    try:
        async with client_for(engine) as client:
            response = await client.get("/ready")
    finally:
        await engine.dispose()
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}  # no detail in the body


async def test_ready_503_when_no_database_configured() -> None:
    async with client_for(None) as client:
        response = await client.get("/ready")
    assert response.status_code == 503


async def test_health_stays_200_when_database_is_down() -> None:
    engine = create_engine("postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nothing")
    try:
        async with client_for(engine) as client:
            response = await client.get("/health")
    finally:
        await engine.dispose()
    assert response.status_code == 200
