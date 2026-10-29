"""Shared request helpers for the appointment endpoint tests."""

import uuid
from typing import Any

from httpx import AsyncClient, Response

from tests.unit.auth_helpers import bearer, claims, roles

SLOT = "2030-01-07T09:00:00+03:00"  # Monday, 06:00 UTC; the pinned "now" is 2030-01-01


def patient(sub: str = "kc-p1") -> dict[str, str]:
    return bearer(claims(sub=sub))


def doctor(sub: str = "kc-doc1") -> dict[str, str]:
    return bearer(claims(sub=sub, realm_access=roles("doctor")))


def admin(*permissions: str, sub: str = "kc-admin") -> dict[str, str]:
    return bearer(claims(sub=sub, realm_access=roles("admin", *permissions)))


async def make_booking(
    client: AsyncClient, doctor_id: uuid.UUID, sub: str = "kc-p1", start: str = SLOT
) -> str:
    """Book through the API and return the appointment id."""
    response = await client.post(
        "/appointments",
        json={"doctor_id": str(doctor_id), "start_at": start},
        headers=patient(sub),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def cancel(
    client: AsyncClient, headers: dict[str, str], appointment_id: str, reason: Any = "Cannot attend"
) -> Response:
    return await client.patch(
        f"/appointments/{appointment_id}/cancel", json={"reason": reason}, headers=headers
    )
