import uuid
from datetime import time

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, Time, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DoctorSchedule(Base):
    """Recurring weekly working window, clinic-local time. Monday = 0."""

    __tablename__ = "doctor_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
        Index("ix_doctor_schedules_doctor_id", "doctor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("doctors.id", ondelete="RESTRICT")
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
