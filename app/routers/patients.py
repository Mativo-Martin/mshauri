import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.deps import current_profile, require_permission_if_admin, require_roles
from app.core.clock import utc_now
from app.db.deps import get_uow
from app.db.uow import UnitOfWork
from app.routers.doctors import get_slot_rules
from app.schemas.appointments import AppointmentList, appointment_list
from app.services.appointment_reads import list_patient_appointments
from app.services.profiles import Profile
from app.services.slots import SlotRules

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get(
    "/{patient_id}/appointments",
    response_model=AppointmentList,
    response_model_exclude_none=True,
    dependencies=[
        Depends(require_roles("patient", "admin")),
        Depends(require_permission_if_admin("view_any")),
    ],
)
async def patient_appointments(
    patient_id: uuid.UUID,
    profile: Annotated[Profile, Depends(current_profile)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    now: Annotated[datetime, Depends(utc_now)],
    rules: Annotated[SlotRules, Depends(get_slot_rules)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AppointmentList:
    """A patient's upcoming booked appointments. Patients: own `id`. Admins: `view_any`."""
    page = await list_patient_appointments(
        uow,
        profile,
        patient_id,
        now=now,
        limit=limit,
        offset=offset,
    )
    return appointment_list(page.rows, page.total, limit, offset, rules.timezone)
