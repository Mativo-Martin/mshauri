import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.auth.deps import current_profile, require_permission_if_admin, require_roles
from app.config import Settings
from app.core.clock import utc_now
from app.core.errors import AppError, ErrorCode
from app.db.deps import get_uow
from app.db.uow import UnitOfWork
from app.repositories import doctors as repo
from app.schemas.appointments import AppointmentList, appointment_list
from app.schemas.doctors import AvailabilityOut, DoctorList, DoctorOut, SlotOut
from app.services.appointment_reads import list_doctor_appointments
from app.services.availability import get_availability
from app.services.profiles import Profile
from app.services.slots import SlotRules

router = APIRouter(
    prefix="/doctors",
    tags=["doctors"],
    dependencies=[Depends(require_roles("patient", "doctor", "admin"))],
)


def get_slot_rules(request: Request) -> SlotRules:
    settings: Settings = request.app.state.settings
    return SlotRules(
        timezone=ZoneInfo(settings.clinic_timezone),
        min_lead_time=timedelta(minutes=settings.min_lead_time_minutes),
        max_horizon_days=settings.max_booking_horizon_days,
    )


@router.get("", response_model=DoctorList)
async def list_doctors(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    specialty: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DoctorList:
    """Active doctors, ordered by name. `specialty` matches case-insensitively."""
    doctors, total = await repo.list_active_doctors(uow.session, specialty, limit, offset)
    return DoctorList(
        items=[DoctorOut(id=d.id, name=d.name, specialty=d.specialty) for d in doctors],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{doctor_id}", response_model=DoctorOut)
async def get_doctor(
    doctor_id: uuid.UUID, uow: Annotated[UnitOfWork, Depends(get_uow)]
) -> DoctorOut:
    doctor = await repo.get_active_doctor(uow.session, doctor_id)
    if doctor is None:
        raise AppError(ErrorCode.DOCTOR_NOT_FOUND)
    return DoctorOut(id=doctor.id, name=doctor.name, specialty=doctor.specialty)


@router.get("/{doctor_id}/availability", response_model=AvailabilityOut)
async def availability(
    doctor_id: uuid.UUID,
    day: Annotated[date, Query(alias="date", description="Clinic-local date, YYYY-MM-DD")],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
) -> AvailabilityOut:
    slots = await get_availability(uow.session, doctor_id, day, now, rules)
    return AvailabilityOut(
        doctor_id=doctor_id,
        date=day,
        timezone=str(rules.timezone),
        slots=[
            SlotOut(
                start_at=s.start_at.astimezone(rules.timezone),
                end_at=s.end_at.astimezone(rules.timezone),
            )
            for s in slots
        ],
    )


@router.get(
    "/{doctor_id}/appointments",
    response_model=AppointmentList,
    response_model_exclude_none=True,
    dependencies=[
        Depends(require_roles("doctor", "admin")),
        Depends(require_permission_if_admin("view_any")),
    ],
)
async def doctor_appointments(
    doctor_id: uuid.UUID,
    profile: Annotated[Profile, Depends(current_profile)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
    start_from: Annotated[
        datetime | None,
        Query(alias="from", description="Inclusive. Default: now. Needs an offset."),
    ] = None,
    start_to: Annotated[
        datetime | None, Query(alias="to", description="Exclusive. Needs an offset.")
    ] = None,
    status: Annotated[Literal["booked", "cancelled", "all"], Query()] = "booked",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AppointmentList:
    """A doctor's appointments by start time. Doctors: own `id` only. Admins: `view_any`."""
    for value in (start_from, start_to):
        if value is not None and value.tzinfo is None:
            raise AppError(ErrorCode.NAIVE_DATETIME)
    if start_from is not None and start_to is not None and start_to <= start_from:
        raise AppError(ErrorCode.VALIDATION_ERROR, "`to` must be after `from`.")
    page = await list_doctor_appointments(
        uow,
        profile,
        doctor_id,
        status=status,
        start_from=start_from or now,
        start_to=start_to,
        limit=limit,
        offset=offset,
    )
    return appointment_list(page.rows, page.total, limit, offset, rules.timezone)
