"""Authentication and route-level authorization dependencies (plan section 10).

current_principal: validates the token. No database access, so read-only endpoints never write.
current_profile:   resolves (or provisions, for patients) the caller's record.
require_roles / require_permission: route-level checks. Ownership is checked in services.
Authentication runs first, so a missing token is a 401 even when the body is also invalid.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from app.auth.schemes import oauth2_scheme
from app.auth.tokens import Principal, TokenValidator
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.engine import get_session_factory
from app.db.uow import UnitOfWork
from app.services.profiles import Profile, resolve_profile


def get_token_validator(request: Request) -> TokenValidator | None:
    validator: TokenValidator | None = getattr(request.app.state, "token_validator", None)
    return validator


async def current_principal(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    validator: Annotated[TokenValidator | None, Depends(get_token_validator)],
) -> Principal:
    if token is None:
        raise AppError(ErrorCode.UNAUTHENTICATED)
    if validator is None:
        raise AppError(ErrorCode.AUTH_UNAVAILABLE)  # auth not configured: fail closed
    return await validator.validate(token)


async def current_profile(
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[async_sessionmaker[AsyncSession] | None, Depends(get_session_factory)],
) -> Profile:
    if factory is None:
        raise AppError(ErrorCode.INTERNAL_ERROR)
    async with UnitOfWork(factory) as uow:
        return await resolve_profile(uow, principal)


def require_roles(*allowed: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if principal.role not in allowed:
            audit(
                "authorize",
                actor_sub=principal.sub,
                role=principal.role,
                outcome="denied",
                reason="role_required",
            )
            raise AppError(ErrorCode.FORBIDDEN)
        return principal

    return dependency


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Admin permission roles. An admin without the permission, or a non-admin, gets 403."""

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if principal.role != "admin" or not principal.has_permission(permission):
            audit(
                "authorize",
                actor_sub=principal.sub,
                role=principal.role,
                outcome="denied",
                reason=f"permission_required:{permission}",
            )
            raise AppError(ErrorCode.FORBIDDEN)
        return principal

    return dependency
