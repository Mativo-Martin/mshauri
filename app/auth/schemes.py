"""OpenAPI security scheme, so Swagger UI's Authorize button runs Authorization Code with PKCE.

These URLs are what the *browser* is sent to, so they use the public issuer. The fallback is for
local documentation only: token validation always uses the configured KEYCLOAK_ISSUER.
"""

from fastapi.security import OAuth2AuthorizationCodeBearer

from app.config import get_settings


def _issuer() -> str:
    return get_settings().keycloak_issuer or "http://localhost:8080/realms/clinic"


oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{_issuer()}/protocol/openid-connect/auth",
    tokenUrl=f"{_issuer()}/protocol/openid-connect/token",
    scheme_name="Keycloak",
    auto_error=False,  # we raise our own 401 so the error shape and code stay consistent
)
