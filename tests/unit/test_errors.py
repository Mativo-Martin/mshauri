from app.core.errors import ERRORS, AppError, ErrorCode


def test_every_code_has_a_spec() -> None:
    assert set(ERRORS) == set(ErrorCode)


def test_registry_matches_the_plan() -> None:
    by_status: dict[int, set[str]] = {}
    for code, spec in ERRORS.items():
        by_status.setdefault(spec.status, set()).add(code.value)
    assert by_status == {
        401: {"UNAUTHENTICATED"},
        403: {"FORBIDDEN", "PROFILE_NOT_PROVISIONED"},
        404: {"DOCTOR_NOT_FOUND", "PATIENT_NOT_FOUND", "APPOINTMENT_NOT_FOUND"},
        409: {
            "SLOT_TAKEN",
            "ALREADY_CANCELLED",
            "APPOINTMENT_CANCELLED",
            "APPOINTMENT_IN_PAST",
            "DOCTOR_UNAVAILABLE",
            "SAME_SLOT",
        },
        422: {
            "VALIDATION_ERROR",
            "NAIVE_DATETIME",
            "SLOT_MISALIGNED",
            "SLOT_IN_PAST",
            "SLOT_TOO_SOON",
            "BEYOND_BOOKING_HORIZON",
            "OUTSIDE_WORKING_HOURS",
        },
        500: {"INTERNAL_ERROR"},
        503: {"AUTH_UNAVAILABLE"},
    }


def test_decisions_9_and_14() -> None:
    assert ERRORS[ErrorCode.SAME_SLOT].status == 409
    assert ERRORS[ErrorCode.OUTSIDE_WORKING_HOURS].status == 422
    assert ERRORS[ErrorCode.DOCTOR_UNAVAILABLE].status == 409


def test_app_error_uses_registry_defaults_and_overrides() -> None:
    assert AppError(ErrorCode.SLOT_TAKEN).detail == ERRORS[ErrorCode.SLOT_TAKEN].message
    custom = AppError(ErrorCode.SLOT_TAKEN, "custom text")
    assert custom.detail == "custom text"
    assert custom.status == 409
