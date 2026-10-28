"""Load seed data (doctors, schedules, exceptions) into the configured database.

Idempotent. Run `alembic upgrade head` first. Synthetic data only.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.db.engine import create_engine, create_session_factory
from app.seeding.load import apply_seed
from app.seeding.parse import SeedError, parse_seed


async def run(seed_dir: Path) -> int:
    url = get_settings().database_url
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        data = parse_seed(seed_dir)
    except SeedError as exc:
        print("Seed data rejected; nothing was written:", file=sys.stderr)
        for message in exc.errors:
            print(f"  - {message}", file=sys.stderr)
        return 1
    engine = create_engine(url)
    try:
        report = await apply_seed(create_session_factory(engine), data)
    finally:
        await engine.dispose()
    print(
        f"Seeded: {report.doctors} doctors, {report.schedules} schedule rows, "
        f"{report.exceptions} exceptions"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=Path("seed"))
    return asyncio.run(run(parser.parse_args().seed_dir))


if __name__ == "__main__":
    sys.exit(main())
