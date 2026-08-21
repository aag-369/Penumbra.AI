"""Append-only audit trail.

Every privacy-relevant operation writes a row: key uploads, portfolio uploads,
advisory runs, admin actions, authentication events. The point is that a
regulator -- or an examiner -- can reconstruct what the system did without the
log itself containing anything sensitive. Ciphertexts and key material are
referenced by fingerprint, never by value.
"""

from __future__ import annotations

import enum
import json
from typing import Any

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import Timestamped, UUIDPrimaryKey


class AuditAction(str, enum.Enum):
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    USER_LOGIN_FAILED = "user_login_failed"
    USER_LOGOUT = "user_logout"
    USER_LOCKED = "user_locked"
    USER_DEACTIVATED = "user_deactivated"
    USER_REACTIVATED = "user_reactivated"

    KEY_REGISTERED = "key_registered"
    KEY_REJECTED_SECRET_PRESENT = "key_rejected_secret_present"
    KEY_REVOKED = "key_revoked"

    SESSION_ESTABLISHED = "session_established"
    SESSION_CLOSED = "session_closed"
    CIPHERTEXT_AUTH_FAILED = "ciphertext_auth_failed"

    PORTFOLIO_UPLOADED = "portfolio_uploaded"
    PORTFOLIO_DELETED = "portfolio_deleted"

    ADVISORY_STARTED = "advisory_started"
    ADVISORY_COMPLETED = "advisory_completed"
    ADVISORY_FAILED = "advisory_failed"

    ADMIN_ACTION = "admin_action"


class AuditSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLog(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "audit_logs"

    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False, length=48), nullable=False, index=True
    )
    severity: Mapped[AuditSeverity] = mapped_column(
        Enum(AuditSeverity, native_enum=False, length=16),
        default=AuditSeverity.INFO,
        nullable=False,
        index=True,
    )

    #: Who performed the action.
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: Who it was performed on, when different (admin actions).
    target_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(36))

    ip_address: Mapped[str | None] = mapped_column(String(45))  # fits IPv6
    user_agent: Mapped[str | None] = mapped_column(String(256))

    #: Structured context. Must never contain plaintext holdings, ciphertext
    #: bodies or key material -- use fingerprints.
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    @property
    def details(self) -> dict[str, Any]:
        return json.loads(self.details_json)

    @details.setter
    def details(self, value: dict[str, Any]) -> None:
        self.details_json = json.dumps(value)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action.value} actor={self.actor_user_id} at={self.created_at}>"
