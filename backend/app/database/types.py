from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def str_enum(enum_cls: type[StrEnum], length: int = 32) -> SAEnum:
    """Persist StrEnum values (not names) as VARCHAR."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda items: [item.value for item in items],
    )


class UTCDateTime(TypeDecorator[datetime]):
    """Store timestamps in UTC and always return timezone-aware values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value
