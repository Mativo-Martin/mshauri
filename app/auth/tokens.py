"""Access-token validation (plan section 10.1). No database access.

Accepts only RS256 access tokens signed by a key in the identity provider's JWKS, issued by the
configured issuer, for the configured audience, and of type Bearer. Every failure to prove a token
valid is a 401 with a generic message; only an unreachable identity provider is a 503.
"""

from dataclasses import dataclass
from typing import Any

import jwt

from app.auth.jwks import JwksCache, KeysUnavailableError, UnknownKeyError
from app.core.errors import AppError, ErrorCode

ALGORITHM = "RS256"
BASE_ROLES = frozenset({"patient", "doctor", "admin"})
PERMISSION_ROLES = frozenset({"book_for_patient", "manage_any", "view_any"})


@dataclass(frozen=True)
class TokenConfig:
    issuer: str
    audience: str
    leeway_seconds: int = 30


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, built from token claims only."""

    sub: str
    roles: frozenset[str]
    name: str | None = None
    email: str | None = None

    @property
    def base_roles(self) -> frozenset[str]:
        return self.roles & BASE_ROLES

    @property
    def role(self) -> str | None:
        """The single base role, or None if there are none or several. Ambiguity is denied."""
        return next(iter(self.base_roles)) if len(self.base_roles) == 1 else None

    @property
    def permissions(self) -> frozenset[str]:
        """Admin permission roles. They count only for an admin."""
        return self.roles & PERMISSION_ROLES if "admin" in self.roles else frozenset()

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def _unauthenticated() -> AppError:
    return AppError(ErrorCode.UNAUTHENTICATED)


def _key_id(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _unauthenticated() from None
    if header.get("alg") != ALGORITHM:  # rejects "none", HS256 and everything else
        raise _unauthenticated()
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise _unauthenticated()
    return kid


def _roles(claims: dict[str, Any]) -> frozenset[str]:
    realm_access = claims.get("realm_access")
    if not isinstance(realm_access, dict):
        return frozenset()
    roles = realm_access.get("roles")
    if not isinstance(roles, list):
        return frozenset()
    return frozenset(role for role in roles if isinstance(role, str))


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class TokenValidator:
    def __init__(self, config: TokenConfig, keys: JwksCache) -> None:
        self._config = config
        self._keys = keys

    async def validate(self, token: str) -> Principal:
        kid = _key_id(token)
        try:
            key = await self._keys.get_key(kid)
        except UnknownKeyError:
            raise _unauthenticated() from None
        except KeysUnavailableError:
            raise AppError(ErrorCode.AUTH_UNAVAILABLE) from None

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                audience=self._config.audience,
                issuer=self._config.issuer,
                leeway=self._config.leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError:
            raise _unauthenticated() from None

        if claims.get("typ") != "Bearer":  # refresh and ID tokens are not access tokens
            raise _unauthenticated()
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise _unauthenticated()
        return Principal(
            sub=sub,
            roles=_roles(claims),
            name=_optional_str(claims.get("name")),
            email=_optional_str(claims.get("email")),
        )
