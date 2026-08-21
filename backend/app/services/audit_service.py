"""Writes the audit trail.

Deliberately narrow: one method, one row. The value is in the discipline of
calling it everywhere something privacy-relevant happens, and in
:func:`_scrub` refusing to record anything that looks like key material or a
ciphertext body.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from fastapi import Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..models.audit_log import AuditAction, AuditLog, AuditSeverity

logger = logging.getLogger(__name__)

#: Keys whose values must never reach the audit table.
_FORBIDDEN_KEYS = {
    "ciphertext", "holdings_ciphertext", "cost_basis_ciphertext", "result_ciphertext",
    "public_context", "private_context", "secret_key", "password", "mac_key", "token",
}

#: Anything longer than this is assumed to be a blob, not a description.
_MAX_VALUE_CHARS = 512


def _scrub(details: dict[str, Any]) -> dict[str, Any]:
    """Drop or truncate values that should not be persisted in an audit row."""
    clean: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _FORBIDDEN_KEYS:
            clean[key] = "<redacted>"
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
            clean[key] = f"<{len(value)} chars omitted>"
            continue
        clean[key] = value
    return clean


class AuditService:
    @staticmethod
    def record(
        db: Session,
        action: AuditAction,
        *,
        actor_user_id: str | None = None,
        target_user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        request: Request | None = None,
        **details: Any,
    ) -> AuditLog:
        """Append one audit row.

        Args:
            action: what happened.
            actor_user_id: who did it.
            target_user_id: who it was done to, for admin actions.
            request: if supplied, client IP and user agent are captured.
            **details: structured context, passed through :func:`_scrub`.
        """
        entry = AuditLog(
            action=action,
            severity=severity,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if request is not None:
            entry.ip_address = _client_ip(request)
            entry.user_agent = (request.headers.get("user-agent") or "")[:256] or None
        entry.details = _scrub(details)
        db.add(entry)
        db.flush()

        log_at = logger.warning if severity is not AuditSeverity.INFO else logger.info
        log_at("audit %s actor=%s target=%s %s", action.value, actor_user_id, target_user_id, entry.details)
        return entry

    @staticmethod
    def recent(
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        actions: Iterable[AuditAction] | None = None,
        user_id: str | None = None,
    ) -> list[AuditLog]:
        """Most recent audit rows, newest first."""
        query = db.query(AuditLog)
        if actions:
            query = query.filter(AuditLog.action.in_(list(actions)))
        if user_id:
            query = query.filter(
                (AuditLog.actor_user_id == user_id) | (AuditLog.target_user_id == user_id)
            )
        return query.order_by(desc(AuditLog.created_at)).offset(skip).limit(limit).all()


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP, honouring one layer of proxy header."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None

