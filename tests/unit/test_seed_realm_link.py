"""The seed links doctors to Keycloak users by id, so the two files must agree."""

import json
from pathlib import Path

from app.seeding.parse import parse_seed

ROOT = Path(__file__).resolve().parents[2]


def test_seeded_doctors_are_linked_to_the_realm_doctor_accounts() -> None:
    realm = json.loads((ROOT / "keycloak" / "realm-clinic.json").read_text())
    user_ids = {user["username"]: user["id"] for user in realm["users"]}
    subs = {d.external_ref: d.keycloak_sub for d in parse_seed(ROOT / "seed").doctors}
    assert subs["DOC-001"] == user_ids["doctor1"]
    assert subs["DOC-002"] == user_ids["doctor2"]
