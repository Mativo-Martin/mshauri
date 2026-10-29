"""Global exception handlers: one error shape, {"detail", "code"}, from one registry."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import ERRORS, AppError, ErrorCode

logger = logging.getLogger(__name__)


def error_response(code: ErrorCode, detail: str | None = None) -> JSONResponse:
    spec = ERRORS[code]
    return JSONResponse(
        status_code=spec.status,
        content={"detail": detail or spec.message, "code": code.value},
    )


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if any(err["type"] == "naive_datetime" for err in errors):
            return error_response(ErrorCode.NAIVE_DATETIME)
        # Field locations only: never echo the submitted values, which may be personal data.
        fields = sorted({".".join(str(part) for part in err["loc"]) for err in errors})
        return error_response(
            ErrorCode.VALIDATION_ERROR, f"Invalid or missing: {', '.join(fields)}"
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Type only: exception messages (especially from the database) can contain values.
        logger.error("unhandled error: %s", type(exc).__name__)
        return error_response(ErrorCode.INTERNAL_ERROR)
