import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScheduleException(Base):
    """Blocked time (leave, closure, unavailable). Hides slots; never cancels bookings."""

    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        CheckConstraint("end_timestamp > start_timestamp", name="end_after_start"),
        CheckConstraint("type IN ('leave', 'closure', 'unavailable')", name="type"),
        Index(
            "ix_schedule_exceptions_doctor_range", "doctor_id", "start_timestamp", "end_timestamp"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("doctors.id", ondelete="RESTRICT")
    )
    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(Text)
    # Free text: never logged.
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
