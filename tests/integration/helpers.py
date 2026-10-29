from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

TABLES = ("doctors", "doctor_schedules", "schedule_exceptions")


async def count_rows(engine: AsyncEngine, table: str) -> int:
    """Test-only: `table` is always one of this module's constants."""
    async with engine.connect() as conn:
        result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


async def table_counts(engine: AsyncEngine) -> dict[str, int]:
    return {table: await count_rows(engine, table) for table in TABLES}
