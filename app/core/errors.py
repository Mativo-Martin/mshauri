"""One registry of error codes (plan section 8). No HTTP or database imports.

Services raise AppError(code); a global handler (added with the first endpoint) turns it into
{"detail": ..., "code": ...} using the status recorded here.
"""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    PROFILE_NOT_PROVISIONED = "PROFILE_NOT_PROVISIONED"
    DOCTOR_NOT_FOUND = "DOCTOR_NOT_FOUND"
    PATIENT_NOT_FOUND = "PATIENT_NOT_FOUND"
    APPOINTMENT_NOT_FOUND = "APPOINTMENT_NOT_FOUND"
    SLOT_TAKEN = "SLOT_TAKEN"
    ALREADY_CANCELLED = "ALREADY_CANCELLED"
    APPOINTMENT_CANCELLED = "APPOINTMENT_CANCELLED"
    APPOINTMENT_IN_PAST = "APPOINTMENT_IN_PAST"
    DOCTOR_UNAVAILABLE = "DOCTOR_UNAVAILABLE"
    SAME_SLOT = "SAME_SLOT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NAIVE_DATETIME = "NAIVE_DATETIME"
    SLOT_MISALIGNED = "SLOT_MISALIGNED"
    SLOT_IN_PAST = "SLOT_IN_PAST"
    SLOT_TOO_SOON = "SLOT_TOO_SOON"
    BEYOND_BOOKING_HORIZON = "BEYOND_BOOKING_HORIZON"
    OUTSIDE_WORKING_HOURS = "OUTSIDE_WORKING_HOURS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str


ERRORS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.UNAUTHENTICATED: ErrorSpec(
        401, "Authentication is required or the token is invalid."
    ),
    ErrorCode.FORBIDDEN: ErrorSpec(403, "You are not allowed to perform this action."),
    ErrorCode.PROFILE_NOT_PROVISIONED: ErrorSpec(403, "No profile is linked to this account."),
    ErrorCode.DOCTOR_NOT_FOUND: ErrorSpec(404, "Doctor not found."),
    ErrorCode.PATIENT_NOT_FOUND: ErrorSpec(404, "Patient not found."),
    ErrorCode.APPOINTMENT_NOT_FOUND: ErrorSpec(404, "Appointment not found."),
    ErrorCode.SLOT_TAKEN: ErrorSpec(409, "Slot is already booked."),
    ErrorCode.ALREADY_CANCELLED: ErrorSpec(409, "Appointment is already cancelled."),
    ErrorCode.APPOINTMENT_CANCELLED: ErrorSpec(409, "Appointment is cancelled."),
    ErrorCode.APPOINTMENT_IN_PAST: ErrorSpec(409, "Appointment has already started."),
    ErrorCode.DOCTOR_UNAVAILABLE: ErrorSpec(409, "Doctor is not available for booking."),
    ErrorCode.SAME_SLOT: ErrorSpec(409, "New time is the same as the current time."),
    ErrorCode.VALIDATION_ERROR: ErrorSpec(422, "Request validation failed."),
    ErrorCode.NAIVE_DATETIME: ErrorSpec(422, "Datetime must include a UTC offset."),
    ErrorCode.SLOT_MISALIGNED: ErrorSpec(422, "Slot must start on a 30-minute boundary."),
    ErrorCode.SLOT_IN_PAST: ErrorSpec(422, "Slot is in the past."),
    ErrorCode.SLOT_TOO_SOON: ErrorSpec(422, "Slot starts too soon to book."),
    ErrorCode.BEYOND_BOOKING_HORIZON: ErrorSpec(422, "Slot is beyond the booking horizon."),
    ErrorCode.OUTSIDE_WORKING_HOURS: ErrorSpec(422, "Slot is outside the doctor's working hours."),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(500, "Internal error."),
    ErrorCode.AUTH_UNAVAILABLE: ErrorSpec(503, "Authentication service is unavailable."),
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or ERRORS[code].message
        super().__init__(self.detail)

    @property
    def status(self) -> int:
        return ERRORS[self.code].status
