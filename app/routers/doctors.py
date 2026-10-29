import uuid
from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.auth.deps import require_roles
from app.config import Settings
from app.core.clock import utc_now
from app.core.errors import AppError, ErrorCode
from app.db.deps import get_uow
from app.db.uow import UnitOfWork
from app.repositories import doctors as repo
from app.schemas.doctors import AvailabilityOut, DoctorList, DoctorOut, SlotOut
from app.services.availability import get_availability
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
