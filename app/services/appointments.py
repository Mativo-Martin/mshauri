"""Changing an existing appointment: cancel and reschedule (plan section 9).

Order of checks is fixed: lock and find (404), then ownership (403), then state (409),
then slot rules (422 or 409).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.uow import UnitOfWork
from app.models import Appointment
from app.repositories import appointments as appointment_repo
from app.repositories import doctors as doctor_repo
from app.repositories.profiles import get_patient
from app.services.profiles import Profile
from app.services.slot_check import check_slot
from app.services.slots import SlotRules


@dataclass(frozen=True)
class AppointmentView:
    appointment: Appointment
    doctor_name: str
    patient_name: str


def can_access(profile: Profile, appointment: Appointment, admin_permission: str) -> bool:
    """Own appointment (patient), own schedule (doctor), or an admin holding the permission."""
    if profile.role == "patient":
        return profile.patient_id is not None and appointment.patient_id == profile.patient_id
    if profile.role == "doctor":
        return profile.doctor_id is not None and appointment.doctor_id == profile.doctor_id
    if profile.role == "admin":
        return profile.principal.has_permission(admin_permission)
    return False


def can_change(profile: Profile, appointment: Appointment) -> bool:
    return can_access(profile, appointment, "manage_any")


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


MAX_ATTEMPTS = 2  # one try plus one retry after a deadlock (plan D13)


async def _reschedule_once(
    uow: UnitOfWork,
    profile: Profile,
    appointment_id: uuid.UUID,
    new_start_at: datetime,
    now: datetime,
    rules: SlotRules,
) -> AppointmentView:
    """One full attempt: lock, ownership, state, slot rules, update. Order is plan section 9."""
    action = "appointment.reschedule"
    view = await load_for_change(uow, profile, appointment_id, action)
    appointment = view.appointment

    if appointment.status == "cancelled":
        raise AppError(ErrorCode.APPOINTMENT_CANCELLED)
    if appointment.start_at <= now:  # in progress or over
        raise AppError(ErrorCode.APPOINTMENT_IN_PAST)
    new_start = new_start_at.astimezone(UTC)
    if new_start == appointment.start_at:
        raise AppError(ErrorCode.SAME_SLOT)

    doctor = await doctor_repo.get_doctor(uow.session, appointment.doctor_id)
    if doctor is None:  # foreign keys make this unreachable
        raise AppError(ErrorCode.INTERNAL_ERROR)
    await check_slot(
        uow,
        doctor_id=doctor.id,
        doctor_active=doctor.is_active,
        start_at=new_start,
        now=now,
        rules=rules,
    )

    try:
        moved = await appointment_repo.move_appointment(uow.session, appointment_id, new_start)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()  # the original row is untouched
        if not appointment_repo.is_slot_conflict(exc):
            raise  # not a slot conflict: a generic 500, never SLOT_TAKEN
        audit(
            action,
            actor_sub=profile.principal.sub,
            role=profile.role,
            outcome="conflict",
            resource_type="appointment",
            resource_id=str(appointment_id),
            reason="slot_taken",
        )
        raise AppError(ErrorCode.SLOT_TAKEN) from None

    audit(
        action,
        actor_sub=profile.principal.sub,
        role=profile.role,
        outcome="success",
        resource_type="appointment",
        resource_id=str(appointment_id),
    )
    return AppointmentView(moved, view.doctor_name, view.patient_name)


async def reschedule_appointment(
    uow: UnitOfWork,
    profile: Profile,
    appointment_id: uuid.UUID,
    new_start_at: datetime,
    now: datetime,
    rules: SlotRules,
) -> AppointmentView:
    """Move an appointment in place. A deadlock retries the whole attempt once, then 409."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await _reschedule_once(uow, profile, appointment_id, new_start_at, now, rules)
        except IntegrityError:
            raise
        except DBAPIError as exc:
            if not appointment_repo.is_deadlock(exc):
                raise
            await uow.rollback()  # releases our locks so the other transaction can finish
            final = attempt == MAX_ATTEMPTS
            audit(
                "appointment.reschedule",
                actor_sub=profile.principal.sub,
                role=profile.role,
                outcome="conflict" if final else "retry",
                resource_type="appointment",
                resource_id=str(appointment_id),
                reason="deadlock",
            )
            if final:
                raise AppError(ErrorCode.SLOT_TAKEN) from None
    raise AppError(ErrorCode.INTERNAL_ERROR)  # unreachable; satisfies the type checker
