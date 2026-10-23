import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at = start_at + interval '30 minutes'", name="duration"),
        # Valid because Nairobi's UTC offset is a whole number of hours (plan section 6).
        CheckConstraint("mod(extract(epoch from start_at), 1800) = 0", name="aligned"),
        CheckConstraint("status IN ('booked', 'cancelled')", name="status"),
        CheckConstraint(
            "(status = 'cancelled' AND cancel_reason IS NOT NULL AND btrim(cancel_reason) <> ''"
            " AND cancelled_at IS NOT NULL AND cancelled_by_sub IS NOT NULL)"
            " OR (status = 'booked' AND cancel_reason IS NULL AND cancelled_at IS NULL"
            " AND cancelled_by_sub IS NULL)",
            name="cancel_fields",
        ),
        # The double-booking guard. Cancelled rows do not hold the slot.
        Index(
            "uq_appointments_doctor_start_booked",
            "doctor_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index("ix_appointments_patient_start", "patient_id", "start_at"),
        Index("ix_appointments_doctor_start", "doctor_id", "start_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("doctors.id", ondelete="RESTRICT")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="RESTRICT")
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    # Free text, may contain sensitive detail: never logged.
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_sub: Mapped[str] = mapped_column(Text)
    cancelled_by_sub: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
