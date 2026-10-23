from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    """Liveness probe. Intentionally has no DB or auth dependency."""
    return {"status": "ok", "version": settings.app_version}
