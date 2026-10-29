"""Booking (plan sections 8 and 9). Decides rules and ownership; never decides HTTP codes."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.uow import UnitOfWork
from app.models import Appointment
from app.repositories import appointments as appointment_repo
from app.repositories import doctors as doctor_repo
from app.repositories.profiles import get_patient
from app.schemas.appointments import BookRequest
from app.services.availability import local_day_bounds
from app.services.profiles import Profile
from app.services.slots import SlotRules, validate_slot


@dataclass(frozen=True)
class BookingResult:
    appointment: Appointment
    doctor_name: str
    patient_name: str
    created: bool  # False for an identical replay


def _resolve_patient_id(profile: Profile, request: BookRequest) -> uuid.UUID:
    """Who the appointment is for. The caller's identity decides, never the body alone."""
    principal = profile.principal
    if profile.role == "patient":
        if profile.patient_id is None:
            raise AppError(ErrorCode.INTERNAL_ERROR)
        if request.patient_id is not None and request.patient_id != profile.patient_id:
            audit(
                "appointment.book",
                actor_sub=principal.sub,
                role=profile.role,
                outcome="denied",
                reason="other_patient",
            )
            raise AppError(ErrorCode.FORBIDDEN)
        return profile.patient_id

    if profile.role == "admin":
        # Permission first (403), then validation (422): the documented order.
        if not principal.has_permission("book_for_patient"):
            audit(
                "appointment.book",
                actor_sub=principal.sub,
                role=profile.role,
                outcome="denied",
                reason="permission_required:book_for_patient",
            )
            raise AppError(ErrorCode.FORBIDDEN)
        if request.patient_id is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Invalid or missing: body.patient_id")
        return request.patient_id

    audit(
        "appointment.book",
        actor_sub=principal.sub,
        role=profile.role,
        outcome="denied",
        reason="role_required",
    )
    raise AppError(ErrorCode.FORBIDDEN)


async def book_appointment(
    uow: UnitOfWork, profile: Profile, request: BookRequest, now: datetime, rules: SlotRules
) -> BookingResult:
    principal = profile.principal
    patient_id = _resolve_patient_id(profile, request)
    session = uow.session

    doctor = await doctor_repo.get_doctor(session, request.doctor_id)
    if doctor is None:
        raise AppError(ErrorCode.DOCTOR_NOT_FOUND)
    patient = await get_patient(session, patient_id)
    if patient is None or patient.anonymized_at is not None:
        raise AppError(ErrorCode.PATIENT_NOT_FOUND)

    # A rollback expires loaded rows, so keep the plain values we still need.
    doctor_id, doctor_name = doctor.id, doctor.name
    patient_name = patient.name

    start_at = request.start_at.astimezone(UTC)
    local_day = start_at.astimezone(rules.timezone).date()
    day_start, day_end = local_day_bounds(local_day, rules)
    windows = await doctor_repo.get_windows(session, doctor_id, local_day.weekday())
    blocked = await doctor_repo.get_blocked_intervals(session, doctor_id, day_start, day_end)
    validate_slot(
        doctor_active=doctor.is_active,
        windows=windows,
        exceptions=blocked,
        start_at=start_at,
        now=now,
        rules=rules,
    )

    on_behalf = "admin_for_patient" if profile.role == "admin" else None
    try:
        appointment = await appointment_repo.insert_booked(
            session, doctor_id, patient_id, start_at, principal.sub
        )
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        if not appointment_repo.is_slot_conflict(exc):
            raise  # not a slot conflict: becomes a generic 500, never SLOT_TAKEN
        existing = await appointment_repo.get_booked(session, doctor_id, start_at)
        if existing is not None and existing.patient_id == patient_id:
            audit(
                "appointment.book",
                actor_sub=principal.sub,
                role=profile.role,
                outcome="replay",
                resource_type="appointment",
                resource_id=str(existing.id),
                reason=on_behalf,
            )
            return BookingResult(existing, doctor_name, patient_name, created=False)
        audit(
            "appointment.book",
            actor_sub=principal.sub,
            role=profile.role,
            outcome="conflict",
            reason="slot_taken",
        )
        raise AppError(ErrorCode.SLOT_TAKEN) from None

    audit(
        "appointment.book",
        actor_sub=principal.sub,
        role=profile.role,
        outcome="success",
        resource_type="appointment",
        resource_id=str(appointment.id),
        reason=on_behalf,
    )
    return BookingResult(appointment, doctor_name, patient_name, created=True)
