import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from app.models import Appointment
from app.schemas.common import OffsetDatetime


class BookRequest(BaseModel):
    # Unknown fields are refused, so a client cannot try to set status or ids we own.
    model_config = ConfigDict(extra="forbid")

    doctor_id: uuid.UUID
    patient_id: uuid.UUID | None = None  # patients: from the token; admins: required
    start_at: OffsetDatetime


class DoctorRef(BaseModel):
    id: uuid.UUID
    name: str


class PatientRef(BaseModel):
    """Name only. Email and phone are never part of an appointment response."""

    id: uuid.UUID
    name: str


class AppointmentOut(BaseModel):
    id: uuid.UUID
    doctor: DoctorRef
    patient: PatientRef
    start_at: datetime
    end_at: datetime
    status: str
    cancel_reason: str | None = None  # present only when cancelled
    cancelled_at: datetime | None = None  # present only when cancelled
    created_at: datetime
    updated_at: datetime


def appointment_out(
    appointment: Appointment, doctor_name: str, patient_name: str, tz: ZoneInfo
) -> AppointmentOut:
    """Build the response with every timestamp in the clinic-local offset."""
    cancelled = appointment.status == "cancelled"
    return AppointmentOut(
        id=appointment.id,
        doctor=DoctorRef(id=appointment.doctor_id, name=doctor_name),
        patient=PatientRef(id=appointment.patient_id, name=patient_name),
        start_at=appointment.start_at.astimezone(tz),
        end_at=appointment.end_at.astimezone(tz),
        status=appointment.status,
        cancel_reason=appointment.cancel_reason if cancelled else None,
        cancelled_at=appointment.cancelled_at.astimezone(tz)
        if cancelled and appointment.cancelled_at
        else None,
        created_at=appointment.created_at.astimezone(tz),
        updated_at=appointment.updated_at.astimezone(tz),
    )


class AppointmentList(BaseModel):
    items: list[AppointmentOut]
    total: int
    limit: int
    offset: int


def appointment_list(
    rows: list[tuple[Appointment, str, str]], total: int, limit: int, offset: int, tz: ZoneInfo
) -> AppointmentList:
    return AppointmentList(
        items=[appointment_out(a, doctor, patient, tz) for a, doctor, patient in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
