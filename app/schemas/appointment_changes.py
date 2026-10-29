from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# Trimmed first, so a reason of spaces is refused. The database CHECK also rejects blanks.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
