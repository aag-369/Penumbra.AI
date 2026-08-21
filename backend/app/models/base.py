"""Shared column types and mixins for the ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware current time. Never use ``datetime.utcnow`` -- it is naive."""
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """A ``DateTime`` that is always timezone-aware in Python.

    SQLite has no native timestamp type, so SQLAlchemy stores datetimes as
    strings and hands them back *naive* regardless of what went in. Subtracting
    a naive value from an aware one raises ``TypeError``, and the failure
    surfaces far from its cause -- typically in a duration calculation, in a
    background task, in production.

    This decorator normalises both directions: anything written is converted to
    UTC, and anything read back is stamped as UTC. PostgreSQL, which does track
    the offset, is unaffected.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class UUIDPrimaryKey:
    """String UUID primary key, portable across SQLite and PostgreSQL."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class Timestamped:
    """``created_at`` / ``updated_at`` maintained by the ORM."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
