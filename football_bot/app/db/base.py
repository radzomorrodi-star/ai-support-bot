from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

# Surrogate PKs: BIGINT on PostgreSQL, INTEGER on SQLite (needed for autoincrement there).
PK = BigInteger().with_variant(Integer, "sqlite")


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes everywhere. Naive values are rejected, never guessed."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use UTC-aware values")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass
