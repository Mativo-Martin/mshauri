import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.auth.deps import current_profile, require_permission_if_admin, require_roles
from app.core.clock import utc_now
from app.db.deps import get_uow
from app.db.uow import UnitOfWork
from app.routers.doctors import get_slot_rules
from app.schemas.appointment_changes import CancelRequest, RescheduleRequest
from app.schemas.appointments import AppointmentOut, BookRequest, appointment_out
from app.services.appointments import cancel_appointment, reschedule_appointment
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


@router.patch(
    "/{appointment_id}/cancel",
    response_model=AppointmentOut,
    response_model_exclude_none=True,
    dependencies=[
        Depends(require_roles("patient", "doctor", "admin")),
        Depends(require_permission_if_admin("manage_any")),
    ],
)
async def cancel(
    appointment_id: uuid.UUID,
    body: CancelRequest,
    profile: Annotated[Profile, Depends(current_profile)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
) -> AppointmentOut:
    """Cancel with a required reason. Patients: own. Doctors: own schedule. Admins: `manage_any`."""
    view = await cancel_appointment(uow, profile, appointment_id, body.reason, now)
    return appointment_out(view.appointment, view.doctor_name, view.patient_name, rules.timezone)


@router.patch(
    "/{appointment_id}/reschedule",
    response_model=AppointmentOut,
    response_model_exclude_none=True,
    dependencies=[
        Depends(require_roles("patient", "doctor", "admin")),
        Depends(require_permission_if_admin("manage_any")),
    ],
)
async def reschedule(
    appointment_id: uuid.UUID,
    body: RescheduleRequest,
    profile: Annotated[Profile, Depends(current_profile)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
) -> AppointmentOut:
    """Move to a new slot, same doctor, same row. Same access rules as cancel."""
    view = await reschedule_appointment(uow, profile, appointment_id, body.new_start_at, now, rules)
    return appointment_out(view.appointment, view.doctor_name, view.patient_name, rules.timezone)
