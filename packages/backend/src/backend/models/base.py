import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


def generate_uuid() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """DateTime that treats DB values as UTC and strips tz on write (MySQL DATETIME is naive)."""

    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value


class UTCDateTimeFsp(UTCDateTime):
    """UTC-aware variant with microsecond precision (MySQL DATETIME(fsp=6))."""

    impl = MySQLDateTime(fsp=6)


class Base(DeclarativeBase):
    pass
