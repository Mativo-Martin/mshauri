"""initial schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")


def _ts(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "doctors",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("specialty", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("keycloak_sub", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.UniqueConstraint("keycloak_sub", name=op.f("uq_doctors_keycloak_sub")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_doctors_external_ref")),
    )

    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, nullable=False),
        sa.Column("keycloak_sub", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.UniqueConstraint("keycloak_sub", name=op.f("uq_patients_keycloak_sub")),
    )

    op.create_table(
        "doctor_schedules",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_doctor_schedules_weekday_range")
        ),
        sa.CheckConstraint(
            "end_time > start_time", name=op.f("ck_doctor_schedules_end_after_start")
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=op.f("fk_doctor_schedules_doctor_id_doctors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctor_schedules")),
    )
    op.create_index(op.f("ix_doctor_schedules_doctor_id"), "doctor_schedules", ["doctor_id"])

    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.CheckConstraint(
            "end_timestamp > start_timestamp",
            name=op.f("ck_schedule_exceptions_end_after_start"),
        ),
        sa.CheckConstraint(
            "type IN ('leave', 'closure', 'unavailable')",
            name=op.f("ck_schedule_exceptions_type"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=op.f("fk_schedule_exceptions_doctor_id_doctors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_exceptions")),
    )
    op.create_index(
        op.f("ix_schedule_exceptions_doctor_range"),
        "schedule_exceptions",
        ["doctor_id", "start_timestamp", "end_timestamp"],
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_sub", sa.Text(), nullable=False),
        sa.Column("cancelled_by_sub", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "end_at = start_at + interval '30 minutes'",
            name=op.f("ck_appointments_duration"),
        ),
        sa.CheckConstraint(
            "mod(extract(epoch from start_at), 1800) = 0",
            name=op.f("ck_appointments_aligned"),
        ),
        sa.CheckConstraint(
            "status IN ('booked', 'cancelled')",
            name=op.f("ck_appointments_status"),
        ),
        sa.CheckConstraint(
            "(status = 'cancelled' AND cancel_reason IS NOT NULL AND btrim(cancel_reason) <> ''"
            " AND cancelled_at IS NOT NULL AND cancelled_by_sub IS NOT NULL)"
            " OR (status = 'booked' AND cancel_reason IS NULL AND cancelled_at IS NULL"
            " AND cancelled_by_sub IS NULL)",
            name=op.f("ck_appointments_cancel_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"],
            ["doctors.id"],
            name=op.f("fk_appointments_doctor_id_doctors"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_appointments_patient_id_patients"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
    )
    op.create_index(
        op.f("uq_appointments_doctor_start_booked"),
        "appointments",
        ["doctor_id", "start_at"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )
    op.create_index(
        op.f("ix_appointments_patient_start"), "appointments", ["patient_id", "start_at"]
    )
    op.create_index(op.f("ix_appointments_doctor_start"), "appointments", ["doctor_id", "start_at"])


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_table("schedule_exceptions")
    op.drop_table("doctor_schedules")
    op.drop_table("patients")
    op.drop_table("doctors")
