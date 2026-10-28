from app.auth.tokens import Principal


def principal(*roles: str) -> Principal:
    return Principal(sub="s", roles=frozenset(roles))


def test_single_base_role() -> None:
    assert principal("patient", "offline_access").role == "patient"
    assert principal("admin", "view_any").role == "admin"


def test_no_base_role_is_none() -> None:
    assert principal("offline_access").role is None
    assert principal().role is None


def test_several_base_roles_are_ambiguous_and_none() -> None:
    assert principal("patient", "doctor").role is None
    assert principal("admin", "doctor").role is None
