from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator
from pydantic_core import PydanticCustomError


def _require_string_or_datetime(value: Any) -> Any:
    if not isinstance(value, (str, datetime)):
        raise PydanticCustomError("datetime_type", "Input should be a valid datetime string")
    return value


def _require_offset(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PydanticCustomError("naive_datetime", "Datetime must include a UTC offset.")
    return value


# A datetime that must carry an offset. The handler turns the error into NAIVE_DATETIME (422).
OffsetDatetime = Annotated[
    datetime, BeforeValidator(_require_string_or_datetime), AfterValidator(_require_offset)
]
