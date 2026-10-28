import logging

from app.auth.jwks import JwksCache, http_fetcher
from app.auth.tokens import TokenConfig, TokenValidator

from app.config import Settings

logger = logging.getLogger(__name__)


def build_token_validator(settings: Settings) -> TokenValidator | None:
    """None when auth is not configured. Protected endpoints then fail closed with 503."""
    if not (settings.keycloak_issuer and settings.keycloak_audience and settings.jwks_url):
        logger.warning(
            "Auth is not configured (KEYCLOAK_ISSUER, KEYCLOAK_AUDIENCE, JWKS_URL): "
            "protected endpoints will return 503"
        )
        return None
    cache = JwksCache(
        http_fetcher(settings.jwks_url),
        ttl_seconds=settings.jwks_ttl_seconds,
        min_refetch_seconds=settings.jwks_min_refetch_seconds,
    )
    return TokenValidator(
        TokenConfig(
            issuer=settings.keycloak_issuer,
            audience=settings.keycloak_audience,
            leeway_seconds=settings.token_leeway_seconds,
        ),
        cache,
    )
