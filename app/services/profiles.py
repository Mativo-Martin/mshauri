import uuid
from dataclasses import dataclass

from app.auth.tokens import Principal
from app.core.audit import audit
from app.core.errors import AppError, ErrorCode
from app.db.uow import UnitOfWork
from app.repositories.profiles import (
    get_doctor_by_sub,
    get_patient_by_sub,
    insert_patient_if_absent,
)


@dataclass(frozen=True)
class Profile:
    principal: Principal
    role: str
    patient_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None


async def resolve_profile(uow: UnitOfWork, principal: Principal) -> Profile:
    role = principal.role
    if role is None:
        # No supported role, or several. Separate accounts per role keep duties separate.
        audit(
            "profile.resolve",
            actor_sub=principal.sub,
            role=None,
            outcome="denied",
            reason="no_single_role",
        )
        raise AppError(ErrorCode.FORBIDDEN)

    if role == "admin":
        return Profile(principal, role, name=principal.name, email=principal.email)

    session = uow.session
    if role == "doctor":
        doctor = await get_doctor_by_sub(session, principal.sub)
        if doctor is None:  # doctors are linked by seed or import, never created here
            audit(
                "profile.resolve",
                actor_sub=principal.sub,
                role=role,
                outcome="denied",
                reason="doctor_not_linked",
            )
            raise AppError(
                ErrorCode.PROFILE_NOT_PROVISIONED,
                "No doctor record is linked to this account.",
            )
        return Profile(principal, role, doctor_id=doctor.id, name=doctor.name)

    # patient
    patient = await get_patient_by_sub(session, principal.sub)
    if patient is None:
        created = await insert_patient_if_absent(
            session,
            principal.sub,
            principal.name or principal.email or "Unnamed patient",
            principal.email,
        )
        await uow.commit()
        patient = await get_patient_by_sub(session, principal.sub)
        if patient is None:  # unreachable: the row exists or another request just created it
            raise AppError(ErrorCode.INTERNAL_ERROR)
        if created:
            audit(
                "profile.provision",
                actor_sub=principal.sub,
                role=role,
                outcome="success",
                resource_type="patient",
                resource_id=str(patient.id),
            )
    return Profile(
        principal,
        role,
        patient_id=patient.id,
        name=patient.name,
        email=patient.email,
        phone=patient.phone,
    )
