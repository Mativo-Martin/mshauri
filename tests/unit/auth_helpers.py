"""Test doubles for auth: generated RSA keys, signed tokens, a fake JWKS endpoint, a fake clock."""

import json
import time
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "http://localhost:8080/realms/clinic"
AUDIENCE = "clinic-api"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private: rsa.RSAPrivateKey

    @classmethod
    def generate(cls, kid: str) -> "SigningKey":
        return cls(kid, rsa.generate_private_key(public_exponent=65537, key_size=2048))

    def jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return jwk


KEY_A = SigningKey.generate("key-a")
KEY_B = SigningKey.generate("key-b")


def claims(*, drop: tuple[str, ...] = (), **overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": [AUDIENCE, "account"],
        "sub": "user-1",
        "typ": "Bearer",
        "iat": now,
        "exp": now + 300,
        "name": "Pat One",
        "email": "pat@example.test",
        "realm_access": {"roles": ["patient"]},
    }
    payload.update(overrides)
    for name in drop:
        payload.pop(name, None)
    return payload


def sign(payload: dict[str, Any], key: SigningKey = KEY_A, *, kid: str | None = None) -> str:
    return jwt.encode(payload, key.private, algorithm="RS256", headers={"kid": kid or key.kid})


def sign_without_kid(payload: dict[str, Any], key: SigningKey = KEY_A) -> str:
    return jwt.encode(payload, key.private, algorithm="RS256")


class FakeJwks:
    """Stands in for the identity provider's JWKS endpoint and counts requests."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = [key.jwk() for key in keys]
        self.calls = 0
        self.fail = False
        self.raw: dict[str, Any] | None = None

    def serve(self, *keys: SigningKey) -> None:
        self.keys = [key.jwk() for key in keys]

    async def __call__(self) -> dict[str, Any]:
        self.calls += 1
        if self.fail:
            raise ConnectionError("identity provider unreachable")
        if self.raw is not None:
            return self.raw
        return {"keys": list(self.keys)}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def bearer(payload: dict[str, Any] | None = None, key: SigningKey = KEY_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {sign(payload or claims(), key)}"}


def roles(*names: str) -> dict[str, list[str]]:
    return {"roles": list(names)}
