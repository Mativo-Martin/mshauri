"""Async JWKS cache (plan section 10.1). PyJWKClient blocks the event loop, so this is our own.

- Keys are cached for `ttl_seconds`.
- An unknown kid triggers a refetch, but at most one fetch per `min_refetch_seconds` across all
  requests, so random kid values cannot force a fetch per request.
- If a fetch fails, cached keys keep being served. A kid that is not cached then raises
  KeysUnavailableError (fail closed): an unreachable identity provider is not an invalid token.
- Only RS256 signing keys are kept; encryption keys in the same set are ignored.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

logger = logging.getLogger(__name__)

Fetcher = Callable[[], Awaitable[dict[str, Any]]]
Clock = Callable[[], float]


class UnknownKeyError(Exception):
    """The key id is not in the key set (the token is not ours): a 401."""


class KeysUnavailableError(Exception):
    """Signing keys cannot be fetched and the needed key is not cached: a 503."""


def parse_signing_keys(jwks: dict[str, Any]) -> dict[str, RSAPublicKey]:
    raw = jwks.get("keys")
    if not isinstance(raw, list):
        raise ValueError("JWKS has no 'keys' list")
    keys: dict[str, RSAPublicKey] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or entry.get("kty") != "RSA":
            continue
        if entry.get("use") not in (None, "sig") or entry.get("alg") not in (None, "RS256"):
            continue  # e.g. Keycloak's RSA-OAEP encryption key
        try:
            key = jwt.PyJWK(entry).key
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            continue
        if isinstance(key, RSAPublicKey):
            keys[kid] = key
    return keys


def http_fetcher(url: str, timeout_seconds: float = 3.0) -> Fetcher:
    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("JWKS response is not an object")
        return data

    return fetch


class JwksCache:
    def __init__(
        self,
        fetch: Fetcher,
        *,
        ttl_seconds: float = 600,
        min_refetch_seconds: float = 30,
        clock: Clock = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._min_refetch = min_refetch_seconds
        self._clock = clock
        self._keys: dict[str, RSAPublicKey] = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._last_attempt_failed = False
        self._lock = asyncio.Lock()

    def _is_fresh(self, now: float) -> bool:
        return self._fetched_at is not None and now - self._fetched_at < self._ttl

    def _may_fetch(self, now: float) -> bool:
        return self._last_attempt is None or now - self._last_attempt >= self._min_refetch

    async def get_key(self, kid: str) -> RSAPublicKey:
        key = self._keys.get(kid)
        if key is not None and self._is_fresh(self._clock()):
            return key
        async with self._lock:  # concurrent callers share one fetch
            now = self._clock()
            key = self._keys.get(kid)
            if key is not None and self._is_fresh(now):
                return key  # refreshed while this caller waited
            if self._may_fetch(now):
                await self._refresh(now)
            key = self._keys.get(kid)
            if key is not None:
                return key  # a stale key is still served while the provider is unreachable
            if self._last_attempt_failed:
                raise KeysUnavailableError
            raise UnknownKeyError(kid)

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now
        try:
            keys = parse_signing_keys(await self._fetch())
            if not keys:
                raise ValueError("no usable signing keys in JWKS")
        except Exception as exc:
            self._last_attempt_failed = True
            # Log the error type only: never the URL, a token or a response body.
            logger.warning("JWKS refresh failed: %s", type(exc).__name__)
            return
        self._keys = keys
        self._fetched_at = now
        self._last_attempt_failed = False
