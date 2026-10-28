"""The realm JSON is the source of truth for auth, so its security properties are tested."""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

REALM_PATH = Path(__file__).resolve().parents[2] / "keycloak" / "realm-clinic.json"
REALM: dict[str, Any] = json.loads(REALM_PATH.read_text())

BASE_ROLES = {"patient", "doctor", "admin"}
PERMISSION_ROLES = {"book_for_patient", "manage_any", "view_any"}
PUBLIC_CLIENTS = ["clinic-docs", "clinic-postman"]


def clients() -> dict[str, dict[str, Any]]:
    return {client["clientId"]: client for client in REALM["clients"]}


def users() -> dict[str, dict[str, Any]]:
    return {user["username"]: user for user in REALM["users"]}


def test_realm_basics() -> None:
    assert REALM["realm"] == "clinic"
    assert REALM["enabled"] is True
    assert REALM["registrationAllowed"] is False
    assert REALM["bruteForceProtected"] is True
    assert REALM["accessTokenLifespan"] == 300  # short, so revoked access expires quickly


def test_roles_match_the_plan() -> None:
    assert {role["name"] for role in REALM["roles"]["realm"]} == BASE_ROLES | PERMISSION_ROLES


def test_no_client_allows_password_or_implicit_grants() -> None:
    for client in REALM["clients"]:
        assert client.get("directAccessGrantsEnabled") is False, client["clientId"]
        assert client.get("implicitFlowEnabled") is False, client["clientId"]


def test_api_client_is_bearer_only() -> None:
    api = clients()["clinic-api"]
    assert api["bearerOnly"] is True
    assert api["standardFlowEnabled"] is False


@pytest.mark.parametrize("client_id", PUBLIC_CLIENTS)
def test_public_clients_use_code_flow_with_pkce(client_id: str) -> None:
    client = clients()[client_id]
    assert client["publicClient"] is True
    assert client["standardFlowEnabled"] is True
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["redirectUris"]
    assert "*" not in " ".join(client["redirectUris"])  # no wildcard redirects


@pytest.mark.parametrize("client_id", PUBLIC_CLIENTS)
def test_tokens_carry_the_api_audience(client_id: str) -> None:
    mappers = clients()[client_id]["protocolMappers"]
    audience = [m for m in mappers if m["protocolMapper"] == "oidc-audience-mapper"]
    assert len(audience) == 1
    config = audience[0]["config"]
    assert config["included.client.audience"] == "clinic-api"
    assert config["access.token.claim"] == "true"


def test_demo_users_and_their_roles() -> None:
    roles = {name: set(user["realmRoles"]) for name, user in users().items()}
    assert roles == {
        "patient1": {"patient"},
        "patient2": {"patient"},
        "doctor1": {"doctor"},
        "doctor2": {"doctor"},
        "admin_full": {"admin"} | PERMISSION_ROLES,
        "admin_view_only": {"admin", "view_any"},
    }


def test_only_admins_hold_permission_roles() -> None:
    for name, user in users().items():
        held = set(user["realmRoles"]) & PERMISSION_ROLES
        assert (not held) or "admin" in user["realmRoles"], name


def test_user_ids_are_unique_uuids() -> None:
    ids = [user["id"] for user in REALM["users"]]
    assert len({uuid.UUID(value) for value in ids}) == len(ids)


def test_demo_users_are_complete_and_not_forced_to_reset() -> None:
    for name, user in users().items():
        assert user["enabled"] is True, name
        assert user["emailVerified"] is True, name
        assert user["email"].endswith("@example.test"), name  # reserved, can never be a real inbox
        assert user["firstName"], name
        assert user["lastName"], name
        credential = user["credentials"][0]
        assert credential["type"] == "password"
        assert credential["temporary"] is False


def test_builtin_admin_cli_is_disabled() -> None:
    """Keycloak creates admin-cli with the password grant on in every realm; the plan forbids it."""
    admin_cli = clients()["admin-cli"]
    assert admin_cli["enabled"] is False
    assert admin_cli["directAccessGrantsEnabled"] is False


def test_session_and_token_hardening() -> None:
    assert REALM["ssoSessionIdleTimeout"] <= 900
    assert REALM["ssoSessionMaxLifespan"] <= 28800
    assert REALM["revokeRefreshToken"] is True
    assert REALM["refreshTokenMaxReuse"] == 0
    assert REALM["defaultSignatureAlgorithm"] == "RS256"
    assert REALM["editUsernameAllowed"] is False


def test_password_policy_is_met_by_the_demo_passwords() -> None:
    assert "length(12)" in REALM["passwordPolicy"]
    for name, user in users().items():
        assert len(user["credentials"][0]["value"]) >= 12, name


def test_authentication_events_are_recorded_without_admin_event_details() -> None:
    assert REALM["eventsEnabled"] is True
    assert REALM["eventsExpiration"] >= 7_776_000  # at least 90 days
    assert "LOGIN_ERROR" in REALM["enabledEventTypes"]
    assert REALM["adminEventsEnabled"] is True
    assert REALM["adminEventsDetailsEnabled"] is False  # representations can hold personal data
