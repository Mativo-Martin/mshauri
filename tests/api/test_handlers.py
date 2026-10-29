from typing import Annotated

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.auth.deps import current_principal
from app.auth.tokens import Principal
from app.main import create_app


class Echo(BaseModel):
    value: int


def build_app() -> FastAPI:
    app = create_app()

    @app.post("/_t/echo")
    async def echo(body: Echo) -> dict[str, int]:
        return {"value": body.value}

    @app.post("/_t/echo-secure")
    async def echo_secure(
        body: Echo, _: Annotated[Principal, Depends(current_principal)]
    ) -> dict[str, int]:
        return {"value": body.value}

    @app.get("/_t/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("secret value pat@example.test")

    return app


async def test_validation_error_uses_the_standard_shape_and_never_echoes_input() -> None:
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/_t/echo", json={"value": "SENSITIVE-INPUT"})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "VALIDATION_ERROR"
    assert "body.value" in body["detail"]
    assert "SENSITIVE-INPUT" not in response.text


async def test_authentication_is_checked_before_the_body() -> None:
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/_t/echo-secure", json={"value": "not-a-number"})
    assert response.status_code == 401  # not 422
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_unexpected_error_is_a_generic_500() -> None:
    transport = ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_t/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal error.", "code": "INTERNAL_ERROR"}
    assert "secret" not in response.text
    assert "example.test" not in response.text
