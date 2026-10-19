from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """MySQL stores UTC without an offset; Python always receives an aware timestamp."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(
            DATETIME(fsp=6) if dialect.name == "mysql" else DateTime(timezone=True)
        )

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        aware = (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
        return aware.replace(tzinfo=None) if dialect.name == "mysql" else aware

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
