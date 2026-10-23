import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, Uuid, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    specialty: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    keycloak_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    # Legacy-system ID: makes imports idempotent and reconcilable.
    external_ref: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
