import uuid

from pydantic import BaseModel


class MeResponse(BaseModel):
    """The caller's own identity. Contact details appear only here, never in other responses."""

    sub: str
    role: str
    permissions: list[str]
    patient_id: uuid.UUID | None
    doctor_id: uuid.UUID | None
    name: str | None
    email: str | None
    phone: str | None
