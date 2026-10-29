from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.data import add_doctor, link_doctor
from tests.api.helpers import SLOT, admin, doctor, make_booking, patient
from tests.unit.auth_helpers import bearer, claims, roles

SLOT_RESCHED = "2030-01-07T09:30:00+03:00"
SLOT_ADMIN_BOOK = "2030-01-07T10:00:00+03:00"


@pytest_asyncio.fixture
async def rbac_env(client: AsyncClient, fresh_db: AsyncEngine) -> dict[str, Any]:
    """Doctor A (kc-doc1), Doctor B (kc-doc2), Patient 1 (kc-p1), Patient 2 (kc-p2),

    and an appointment for Patient 1 with Doctor A.
    """
    doc_a = await add_doctor(fresh_db, "Dr A")
    await link_doctor(fresh_db, doc_a, "kc-doc1")

    doc_b = await add_doctor(fresh_db, "Dr B")
    await link_doctor(fresh_db, doc_b, "kc-doc2")

    pat1_id = (await client.get("/me", headers=patient("kc-p1"))).json()["patient_id"]
    pat2_id = (await client.get("/me", headers=patient("kc-p2"))).json()["patient_id"]

    appt_id = await make_booking(client, doc_a, "kc-p1", SLOT)

    return {
        "doc_a": doc_a,
        "doc_b": doc_b,
        "pat1_id": pat1_id,
        "pat2_id": pat2_id,
        "appt_id": appt_id,
    }


def get_headers(who: str) -> dict[str, str]:
    match who:
        case "anon":
            return {}
        case "no_role":
            return bearer(claims(realm_access=roles("offline_access")))
        case "patient_owner":
            return patient("kc-p1")
        case "patient_other":
            return patient("kc-p2")
        case "doctor_owner":
            return doctor("kc-doc1")
        case "doctor_other":
            return doctor("kc-doc2")
        case "admin_plain":
            return admin()
        case "admin_book":
            return admin("book_for_patient")
        case "admin_manage":
            return admin("manage_any")
        case "admin_view":
            return admin("view_any")
        case _:
            raise ValueError(f"Unknown persona: {who}")


MATRIX = [
    # --- Public endpoints ---
    ("health", "anon", 200),
    ("health", "patient_owner", 200),
    ("ready", "anon", 200),
    ("ready", "patient_owner", 200),
    # --- /me ---
    ("me", "anon", 401),
    ("me", "no_role", 403),
    ("me", "patient_owner", 200),
    ("me", "doctor_owner", 200),
    ("me", "admin_plain", 200),
    # --- GET /doctors ---
    ("doctors", "anon", 401),
    ("doctors", "no_role", 403),
    ("doctors", "patient_owner", 200),
    ("doctors", "doctor_owner", 200),
    ("doctors", "admin_plain", 200),
    # --- GET /doctors/{id}/availability ---
    ("availability", "anon", 401),
    ("availability", "no_role", 403),
    ("availability", "patient_owner", 200),
    ("availability", "doctor_owner", 200),
    ("availability", "admin_plain", 200),
    # --- GET /appointments/{id} (Appointment read) ---
    ("read_appt", "anon", 401),
    ("read_appt", "no_role", 403),
    ("read_appt", "patient_owner", 200),
    ("read_appt", "patient_other", 403),
    ("read_appt", "doctor_owner", 200),
    ("read_appt", "doctor_other", 403),
    ("read_appt", "admin_plain", 403),
    ("read_appt", "admin_manage", 403),
    ("read_appt", "admin_book", 403),
    ("read_appt", "admin_view", 200),
    # --- PATCH /appointments/{id}/cancel ---
    ("cancel", "anon", 401),
    ("cancel", "no_role", 403),
    ("cancel", "patient_owner", 200),
    ("cancel", "patient_other", 403),
    ("cancel", "doctor_owner", 200),
    ("cancel", "doctor_other", 403),
    ("cancel", "admin_plain", 403),
    ("cancel", "admin_view", 403),
    ("cancel", "admin_book", 403),
    ("cancel", "admin_manage", 200),
    # --- PATCH /appointments/{id}/reschedule ---
    ("reschedule", "anon", 401),
    ("reschedule", "no_role", 403),
    ("reschedule", "patient_owner", 200),
    ("reschedule", "patient_other", 403),
    ("reschedule", "doctor_owner", 200),
    ("reschedule", "doctor_other", 403),
    ("reschedule", "admin_plain", 403),
    ("reschedule", "admin_view", 403),
    ("reschedule", "admin_book", 403),
    ("reschedule", "admin_manage", 200),
    # --- GET /patients/{id}/appointments ---
    ("patient_appts", "anon", 401),
    ("patient_appts", "no_role", 403),
    ("patient_appts", "patient_owner", 200),
    ("patient_appts", "patient_other", 403),
    ("patient_appts", "doctor_owner", 403),
    ("patient_appts", "admin_plain", 403),
    ("patient_appts", "admin_manage", 403),
    ("patient_appts", "admin_book", 403),
    ("patient_appts", "admin_view", 200),
    # --- GET /doctors/{id}/appointments ---
    ("doctor_appts", "anon", 401),
    ("doctor_appts", "no_role", 403),
    ("doctor_appts", "patient_owner", 403),
    ("doctor_appts", "doctor_owner", 200),
    ("doctor_appts", "doctor_other", 403),
    ("doctor_appts", "admin_plain", 403),
    ("doctor_appts", "admin_manage", 403),
    ("doctor_appts", "admin_book", 403),
    ("doctor_appts", "admin_view", 200),
    # --- POST /appointments (Patient self-booking) ---
    ("book_self", "anon", 401),
    ("book_self", "no_role", 403),
    ("book_self", "patient_owner", 201),
    ("book_self", "doctor_owner", 403),
    ("book_self", "admin_plain", 403),  # admin without book_for_patient is forbidden
    ("book_self", "admin_book", 422),  # admin with book_for_patient missing patient_id gets 422
    # --- POST /appointments (Admin booking on behalf of patient) ---
    ("book_on_behalf", "anon", 401),
    ("book_on_behalf", "no_role", 403),
    ("book_on_behalf", "patient_other", 403),  # patient cannot book for other
    ("book_on_behalf", "doctor_owner", 403),
    ("book_on_behalf", "admin_plain", 403),
    ("book_on_behalf", "admin_view", 403),
    ("book_on_behalf", "admin_manage", 403),
    ("book_on_behalf", "admin_book", 201),
]


@pytest.mark.parametrize(("action", "who", "expected_status"), MATRIX)
async def test_rbac_matrix(
    client: AsyncClient,
    rbac_env: dict[str, Any],
    action: str,
    who: str,
    expected_status: int,
) -> None:
    headers = get_headers(who)
    doc_a = rbac_env["doc_a"]
    pat1_id = rbac_env["pat1_id"]
    appt_id = rbac_env["appt_id"]

    match action:
        case "health":
            res = await client.get("/health", headers=headers)
        case "ready":
            res = await client.get("/ready", headers=headers)
        case "me":
            res = await client.get("/me", headers=headers)
        case "doctors":
            res = await client.get("/doctors", headers=headers)
        case "availability":
            res = await client.get(
                f"/doctors/{doc_a}/availability",
                params={"date": "2030-01-07"},
                headers=headers,
            )
        case "read_appt":
            res = await client.get(f"/appointments/{appt_id}", headers=headers)
        case "cancel":
            res = await client.patch(
                f"/appointments/{appt_id}/cancel",
                json={"reason": "Test cancel reason"},
                headers=headers,
            )
        case "reschedule":
            res = await client.patch(
                f"/appointments/{appt_id}/reschedule",
                json={"new_start_at": SLOT_RESCHED},
                headers=headers,
            )
        case "patient_appts":
            res = await client.get(f"/patients/{pat1_id}/appointments", headers=headers)
        case "doctor_appts":
            res = await client.get(f"/doctors/{doc_a}/appointments", headers=headers)
        case "book_self":
            # Book a new distinct slot
            res = await client.post(
                "/appointments",
                json={"doctor_id": str(doc_a), "start_at": "2030-01-07T11:00:00+03:00"},
                headers=headers,
            )
        case "book_on_behalf":
            # Book for Patient 1 with explicit patient_id
            res = await client.post(
                "/appointments",
                json={
                    "doctor_id": str(doc_a),
                    "patient_id": str(pat1_id),
                    "start_at": SLOT_ADMIN_BOOK,
                },
                headers=headers,
            )
        case _:
            raise ValueError(f"Unknown action: {action}")

    assert res.status_code == expected_status, (
        f"Failed {action} for {who}: expected {expected_status}, got {res.status_code}: {res.text}"
    )
    if expected_status == 401:
        assert res.json()["code"] == "UNAUTHENTICATED"
    elif expected_status == 403:
        assert res.json()["code"] in ("FORBIDDEN", "PROFILE_NOT_PROVISIONED")
