from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.auth.setup import build_token_validator
from app.config import Settings, get_settings
from app.core.audit import configure_audit_logging
from app.core.handlers import register_handlers
from app.db.engine import create_engine, create_session_factory
from app.routers import appointments, doctors, health, me, patients


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_audit_logging()
    engine = create_engine(settings.database_url) if settings.database_url else None
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine) if engine is not None else None
    app.state.token_validator = build_token_validator(settings)
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    app = FastAPI(
        title=config.app_name,
        version=config.app_version,
        lifespan=lifespan,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.docs_enabled else None,
        swagger_ui_init_oauth={
            "clientId": config.docs_oauth_client_id,
            "usePkceWithAuthorizationCodeGrant": True,
            "scopes": "openid",
        },
    )
    app.state.settings = config
    register_handlers(app)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(doctors.router)
    app.include_router(appointments.router)
    app.include_router(patients.router)

    if config.docs_enabled:

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse("/docs")

    return app


app = create_app()
