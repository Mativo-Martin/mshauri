"""Helpers for tests that need a real Postgres. Uses throwaway databases on the dev server."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[2]


def base_url() -> str:
    url = get_settings().database_url
    if not url:
        pytest.fail("DATABASE_URL is not set. Run `make db-up` and see .env.example.")
    return url


def db_url(database: str) -> str:
    return make_url(base_url()).set(database=database).render_as_string(hide_password=False)


async def recreate_database(database: str) -> None:
    admin = create_async_engine(
        db_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{database}"'))
    await admin.dispose()


def run_alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    )


async def table_names(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {str(row[0]) for row in rows}
    await engine.dispose()
    return names
