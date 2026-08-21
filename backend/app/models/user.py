"""User accounts.

Passwords are stored only as bcrypt hashes. There is no column anywhere in this
schema that holds a CKKS secret key, and there is no code path that would write
one -- see :mod:`app.models.encryption_key`.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UTCDateTime, UUIDPrimaryKey

if TYPE_CHECKING:
    from .advisory_job import AdvisoryJob
    from .agent_conversation import AgentConversation
    from .encryption_key import EncryptionKey
    from .portfolio import Portfolio


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16), default=UserRole.USER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    #: Consecutive failed logins. Reset on success; drives lockout.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)

    #: Bumped on logout and on password change. Any JWT carrying an older
    #: value is rejected, which is how logout invalidates tokens without a
    #: server-side blacklist.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    portfolios: Mapped[list["Portfolio"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    encryption_keys: Mapped[list["EncryptionKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    advisory_jobs: Mapped[list["AdvisoryJob"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["AgentConversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role.value} active={self.is_active}>"
