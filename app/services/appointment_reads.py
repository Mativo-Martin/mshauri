"""Reading appointments (plan sections 8 and 10.5). Reads take no row locks and never commit."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.uow import UnitOfWork
from app.repositories import appointments as appointment_repo
from app.repositories import doctors as doctor_repo
from app.repositories.appointments import AppointmentRow
from app.repositories.profiles import get_patient
from app.services.appointments import AppointmentView, can_access
from app.services.profiles import Profile

StatusFilter = Literal["booked", "cancelled", "all"]
STATUSES: dict[str, tuple[str, ...]] = {
    "booked": ("booked",),
    "cancelled": ("cancelled",),
    "all": ("booked", "cancelled"),
}


@dataclass(frozen=True)
class AppointmentPage:
    rows: list[AppointmentRow]
    total: int


def _deny(profile: Profile, action: str, reason: str, resource_id: str | None = None) -> AppError:
    audit(
        action,
        actor_sub=profile.principal.sub,
        role=profile.role,
        outcome="denied",
        resource_type="appointment",
        resource_id=resource_id,
        reason=reason,
    )
    return AppError(ErrorCode.FORBIDDEN)


async def read_appointment(
    uow: UnitOfWork, profile: Profile, appointment_id: uuid.UUID
) -> AppointmentView:
    """404 if absent, 403 if the caller may not see it. Patients: own. Doctors: own schedule."""
    session = uow.session
    appointment = await appointment_repo.get_by_id(session, appointment_id)
    if appointment is None:
        raise AppError(ErrorCode.APPOINTMENT_NOT_FOUND)
    if not can_access(profile, appointment, "view_any"):
        raise _deny(profile, "appointment.read", "not_owner", str(appointment.id))
    doctor = await doctor_repo.get_doctor(session, appointment.doctor_id)
    patient = await get_patient(session, appointment.patient_id)
    if doctor is None or patient is None:  # foreign keys make this unreachable
        raise AppError(ErrorCode.INTERNAL_ERROR)
    return AppointmentView(appointment, doctor.name, patient.name)


async def list_doctor_appointments(
    uow: UnitOfWork,
    profile: Profile,
    doctor_id: uuid.UUID,
    *,
    status: StatusFilter,
    start_from: datetime,
    start_to: datetime | None,
    limit: int,
    offset: int,
) -> AppointmentPage:
    """A doctor sees only their own list (403 before any 404). Admins need view_any (route)."""
    session = uow.session
    if profile.role == "doctor":
        if profile.doctor_id != doctor_id:
            raise _deny(profile, "doctor.appointments.list", "not_own_schedule")
    elif await doctor_repo.get_doctor(session, doctor_id) is None:
        raise AppError(ErrorCode.DOCTOR_NOT_FOUND)

    rows, total = await appointment_repo.list_with_names(
        session,
        statuses=STATUSES[status],
        doctor_id=doctor_id,
        start_from=start_from,
        start_to=start_to,
        limit=limit,
        offset=offset,
    )
    return AppointmentPage(rows, total)


async def list_patient_appointments(
    uow: UnitOfWork,
    profile: Profile,
    patient_id: uuid.UUID,
    *,
    now: datetime,
    limit: int,
    offset: int,
) -> AppointmentPage:
    """A patient sees only their own upcoming booked list (403 before any 404).

    Admins need view_any (route).
    """
    session = uow.session
    if profile.role == "patient":
        if profile.patient_id != patient_id:
            raise _deny(profile, "patient.appointments.list", "not_own_appointments")
    elif await get_patient(session, patient_id) is None:
        raise AppError(ErrorCode.PATIENT_NOT_FOUND)

    rows, total = await appointment_repo.list_with_names(
        session,
        statuses=("booked",),
        patient_id=patient_id,
        start_from=now,
        limit=limit,
        offset=offset,
    )
    return AppointmentPage(rows, total)
