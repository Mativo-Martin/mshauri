from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.deps import current_profile
from app.schemas.me import MeResponse
from app.services.profiles import Profile

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def me(profile: Annotated[Profile, Depends(current_profile)]) -> MeResponse:
    """Who am I: identity, role, admin permissions, and my own patient or doctor id."""
    return MeResponse(
        sub=profile.principal.sub,
        role=profile.role,
        permissions=sorted(profile.principal.permissions),
        patient_id=profile.patient_id,
        doctor_id=profile.doctor_id,
        name=profile.name,
        email=profile.email,
        phone=profile.phone,
    )
