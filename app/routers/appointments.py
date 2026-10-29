from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth.deps import current_profile, require_roles
from app.core.clock import utc_now
from app.db.deps import get_uow
from app.db.uow import UnitOfWork
from app.routers.doctors import get_slot_rules
from app.schemas.appointments import AppointmentOut, BookRequest, appointment_out
from app.services.booking import book_appointment
from app.services.profiles import Profile
from app.services.slots import SlotRules

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post(
    "",
    response_model=AppointmentOut,
    response_model_exclude_none=True,
    status_code=201,
    responses={
        200: {"model": AppointmentOut, "description": "Identical replay: the existing booking"}
    },
    # Doctors are refused here, before a profile is looked up.
    dependencies=[Depends(require_roles("patient", "admin"))],
)
async def book(
    body: BookRequest,
    response: Response,
    profile: Annotated[Profile, Depends(current_profile)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
) -> AppointmentOut:
    """Book a 30-minute slot. Patients book for themselves; admins need `book_for_patient`."""
    result = await book_appointment(uow, profile, body, now, rules)
    if not result.created:
        response.status_code = 200  # same patient, same doctor, same slot: a safe retry
    return appointment_out(
        result.appointment, result.doctor_name, result.patient_name, rules.timezone
    )
