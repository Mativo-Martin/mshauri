from typing import Any

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


def client_for(settings: Settings | None = None) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app(settings)), base_url="http://test")


async def test_root_redirects_to_swagger_ui() -> None:
    async with client_for() as client:
        response = await client.get("/")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"


async def test_swagger_ui_is_configured_for_pkce_with_the_docs_client() -> None:
    async with client_for() as client:
        response = await client.get("/docs")
    assert response.status_code == 200
    assert "usePkceWithAuthorizationCodeGrant" in response.text
    assert "clinic-docs" in response.text


async def test_openapi_describes_the_keycloak_authorization_code_flow() -> None:
    async with client_for() as client:
        schema: dict[str, Any] = (await client.get("/openapi.json")).json()
    scheme = schema["components"]["securitySchemes"]["Keycloak"]
    assert scheme["type"] == "oauth2"
    flow = scheme["flows"]["authorizationCode"]
    assert flow["authorizationUrl"].endswith("/protocol/openid-connect/auth")
    assert flow["tokenUrl"].endswith("/protocol/openid-connect/token")
    assert {"Keycloak": []} in schema["paths"]["/me"]["get"]["security"]


async def test_docs_can_be_switched_off() -> None:
    async with client_for(Settings(docs_enabled=False)) as client:
        for path in ("/", "/docs", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path
        assert (await client.get("/health")).status_code == 200


async def test_clinic_docs_redirect_uri_matches_what_swagger_uses() -> None:
    """Swagger UI returns to /docs/oauth2-redirect; the realm must allow exactly that."""
    import json
    from pathlib import Path

    realm = json.loads(
        (Path(__file__).resolve().parents[2] / "keycloak" / "realm-clinic.json").read_text()
    )
    docs = next(c for c in realm["clients"] if c["clientId"] == "clinic-docs")
    assert "http://localhost:8000/docs/oauth2-redirect" in docs["redirectUris"]
