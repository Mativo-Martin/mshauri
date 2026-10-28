import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.db.engine import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Liveness probe. Intentionally has no DB or auth dependency."""
    return {"status": "ok", "version": settings.app_version}


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content={"status": "unavailable"})


@router.get("/ready")
async def ready(engine: Annotated[AsyncEngine | None, Depends(get_engine)]) -> JSONResponse:
    """Readiness probe: 200 only if the database answers. The body never carries detail."""
    if engine is None:
        return _unavailable()
    try:
        async with asyncio.timeout(3), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        # Any failure (refused, timeout, auth) means not ready; the cause stays out of the body.
        return _unavailable()
    return JSONResponse(content={"status": "ready"})
