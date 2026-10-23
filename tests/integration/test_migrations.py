from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from tests.integration.db import db_url, recreate_database, run_alembic, table_names

APP_TABLES = {
    "doctors",
    "doctor_schedules",
    "schedule_exceptions",
    "patients",
    "appointments",
}


async def test_upgrade_downgrade_roundtrip() -> None:
    await recreate_database("mshauri_migration_test")
    url = db_url("mshauri_migration_test")

    run_alembic(url, "upgrade", "head")
    assert await table_names(url) >= APP_TABLES

    run_alembic(url, "downgrade", "base")
    assert not (APP_TABLES & await table_names(url))

    run_alembic(url, "upgrade", "head")  # re-applies cleanly
    assert await table_names(url) >= APP_TABLES


def _diff(sync_conn: Connection) -> list[Any]:
    return list(compare_metadata(MigrationContext.configure(sync_conn), Base.metadata))


async def test_models_match_migration(migrated_db_url: str) -> None:
    """Catches drift between the ORM models and the hand-written migration."""
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    await engine.dispose()
    assert diff == []
