import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DoctorOut(BaseModel):
    """Directory view. No Keycloak subject, no legacy reference, no contact details."""

    id: uuid.UUID
    name: str
    specialty: str | None


class DoctorList(BaseModel):
    items: list[DoctorOut]
    total: int
    limit: int
    offset: int


class SlotOut(BaseModel):
    start_at: datetime  # UTC
    end_at: datetime  # UTC


class AvailabilityOut(BaseModel):
    doctor_id: uuid.UUID
    date: date  # clinic-local calendar date that was asked for
    timezone: str  # the clinic timezone that date is interpreted in
    slots: list[SlotOut]
