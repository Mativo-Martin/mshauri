from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import OffsetDatetime

# Trimmed first, so a reason of spaces is refused. The database CHECK also rejects blanks.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class RescheduleRequest(BaseModel):
    # Same doctor, same row: the body carries only the new time. Naive datetimes are refused
    # by OffsetDatetime, exactly as when booking.
    model_config = ConfigDict(extra="forbid")

    new_start_at: OffsetDatetime
