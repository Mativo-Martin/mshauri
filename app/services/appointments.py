"""Changing an existing appointment: cancel now, reschedule next (plan section 9).

Order of checks is fixed: lock and find (404), then ownership (403), then state (409).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.uow import UnitOfWork
from app.models import Appointment
from app.repositories import appointments as appointment_repo
from app.repositories import doctors as doctor_repo
from app.repositories.profiles import get_patient
from app.services.profiles import Profile


@dataclass(frozen=True)
class AppointmentView:
    appointment: Appointment
    doctor_name: str
    patient_name: str


def can_change(profile: Profile, appointment: Appointment) -> bool:
    """Own appointment (patient), own schedule (doctor), or an admin holding manage_any."""
    if profile.role == "patient":
        return profile.patient_id is not None and appointment.patient_id == profile.patient_id
    if profile.role == "doctor":
        return profile.doctor_id is not None and appointment.doctor_id == profile.doctor_id
    if profile.role == "admin":
        return profile.principal.has_permission("manage_any")
    return False


async def load_for_change(
    uow: UnitOfWork, profile: Profile, appointment_id: uuid.UUID, action: str
) -> AppointmentView:
    """Lock the appointment, 404 if absent, 403 if the caller may not change it."""
    session = uow.session
    appointment = await appointment_repo.get_for_update(session, appointment_id)
    if appointment is None:
        raise AppError(ErrorCode.APPOINTMENT_NOT_FOUND)
    if not can_change(profile, appointment):
        audit(
            action,
            actor_sub=profile.principal.sub,
            role=profile.role,
            outcome="denied",
            resource_type="appointment",
            resource_id=str(appointment.id),
            reason="not_owner",
        )
        raise AppError(ErrorCode.FORBIDDEN)
    doctor = await doctor_repo.get_doctor(session, appointment.doctor_id)
    patient = await get_patient(session, appointment.patient_id)
    if doctor is None or patient is None:  # foreign keys make this unreachable
        raise AppError(ErrorCode.INTERNAL_ERROR)
    return AppointmentView(appointment, doctor.name, patient.name)


async def cancel_appointment(
    uow: UnitOfWork, profile: Profile, appointment_id: uuid.UUID, reason: str, now: datetime
) -> AppointmentView:
    action = "appointment.cancel"
    view = await load_for_change(uow, profile, appointment_id, action)
    appointment = view.appointment

    if appointment.status == "cancelled":
        raise AppError(ErrorCode.ALREADY_CANCELLED)
    if appointment.start_at <= now:  # in progress or over: cannot be cancelled
        raise AppError(ErrorCode.APPOINTMENT_IN_PAST)

    cancelled = await appointment_repo.mark_cancelled(
        uow.session, appointment.id, reason, now, profile.principal.sub
    )
    await uow.commit()
    audit(
        action,
        actor_sub=profile.principal.sub,
        role=profile.role,
        outcome="success",
        resource_type="appointment",
        resource_id=str(cancelled.id),
    )
    return AppointmentView(cancelled, view.doctor_name, view.patient_name)
