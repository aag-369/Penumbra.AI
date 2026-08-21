"""Administrator endpoints: users, audit trail, health, analytics.

An administrator can see who used the system, when, and how much ciphertext they
stored. An administrator cannot see a single holding. That is not an access-control
decision that could be reversed with a config flag -- the server has no secret
key, so there is nothing to grant access *to*. It is worth being explicit about
in the write-up, because "trust the operator" is exactly the assumption this
project set out to remove.
"""

from __future__ import annotations

import statistics
import time

from fastapi import APIRouter
from sqlalchemy import func, text

from ....config import settings
from ....database import engine
from ....models.advisory_job import AdvisoryJob, JobStatus
from ....models.audit_log import AuditAction, AuditLog, AuditSeverity
from ....models.base import utcnow
from ....models.encryption_key import EncryptionKey
from ....models.portfolio import Portfolio
from ....models.user import User, UserRole
from ....schemas.admin_schema import (
    AdminUserOut,
    AdvisoryAnalytics,
    AuditLogOut,
    EncryptionStats,
    SystemHealth,
)
from ....schemas.common import Message
from ....services.audit_service import AuditService
from ....services.portfolio_service import ValidationFailed
from ..dependencies import AdminUser, Channel, DbSession, Keystore, Req

router = APIRouter()

_STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[AdminUserOut])
def list_users(_admin: AdminUser, db: DbSession, skip: int = 0, limit: int = 100) -> list[AdminUserOut]:
    """All users with per-user counts."""
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(min(limit, 500)).all()
    now = utcnow()
    return [
        AdminUserOut(
            id=u.id,
            email=u.email,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            last_activity_at=u.last_activity_at,
            is_locked=bool(u.locked_until and u.locked_until > now),
            n_portfolios=db.query(func.count(Portfolio.id)).filter(Portfolio.user_id == u.id).scalar() or 0,
            n_advisory_jobs=db.query(func.count(AdvisoryJob.id)).filter(AdvisoryJob.user_id == u.id).scalar() or 0,
            n_keys=db.query(func.count(EncryptionKey.id)).filter(EncryptionKey.user_id == u.id).scalar() or 0,
        )
        for u in users
    ]


@router.post("/users/{user_id}/deactivate", response_model=Message)
def deactivate_user(user_id: str, admin: AdminUser, db: DbSession, request: Req) -> Message:
    """Deactivate an account and invalidate its tokens."""
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise ValidationFailed("an administrator cannot deactivate their own account")
    user.is_active = False
    user.token_version += 1
    AuditService.record(
        db,
        AuditAction.USER_DEACTIVATED,
        actor_user_id=admin.id,
        target_user_id=user.id,
        request=request,
        severity=AuditSeverity.WARNING,
    )
    db.commit()
    return Message(message=f"{user.email} deactivated and signed out")


@router.post("/users/{user_id}/reactivate", response_model=Message)
def reactivate_user(user_id: str, admin: AdminUser, db: DbSession, request: Req) -> Message:
    """Reactivate an account and clear any lockout."""
    user = _get_user(db, user_id)
    user.is_active = True
    user.failed_login_count = 0
    user.locked_until = None
    AuditService.record(
        db,
        AuditAction.USER_REACTIVATED,
        actor_user_id=admin.id,
        target_user_id=user.id,
        request=request,
    )
    db.commit()
    return Message(message=f"{user.email} reactivated")


@router.post("/users/{user_id}/role", response_model=Message)
def set_role(user_id: str, role: UserRole, admin: AdminUser, db: DbSession, request: Req) -> Message:
    """Change a user's role."""
    user = _get_user(db, user_id)
    if user.id == admin.id and role is not UserRole.ADMIN:
        raise ValidationFailed("an administrator cannot demote themselves")
    previous, user.role = user.role.value, role
    user.token_version += 1  # role is a JWT claim, so old tokens must not survive
    AuditService.record(
        db,
        AuditAction.ADMIN_ACTION,
        actor_user_id=admin.id,
        target_user_id=user.id,
        request=request,
        severity=AuditSeverity.WARNING,
        change="role",
        previous=previous,
        new=role.value,
    )
    db.commit()
    return Message(message=f"{user.email} is now {role.value}")


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    _admin: AdminUser,
    db: DbSession,
    skip: int = 0,
    limit: int = 200,
    action: AuditAction | None = None,
    severity: AuditSeverity | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """The audit trail, newest first."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if severity:
        query = query.filter(AuditLog.severity == severity)
    if user_id:
        query = query.filter(
            (AuditLog.actor_user_id == user_id) | (AuditLog.target_user_id == user_id)
        )
    rows = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(min(limit, 1000)).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "severity": r.severity,
            "actor_user_id": r.actor_user_id,
            "target_user_id": r.target_user_id,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "ip_address": r.ip_address,
            "details": r.details,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Health and analytics
# ---------------------------------------------------------------------------


@router.get("/system-health", response_model=SystemHealth)
def system_health(_admin: AdminUser, db: DbSession, channel: Channel) -> SystemHealth:
    """Liveness and latency of each subsystem.

    The crypto self-test is a real CKKS round-trip on synthetic data using a
    throwaway keypair, not a version check. If the FHE layer has broken, this is
    where it shows up.
    """
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_ok, db_ms = True, (time.perf_counter() - started) * 1000
    except Exception:
        db_ok, db_ms = False, -1.0

    crypto_ok, crypto_ms = _crypto_selftest()
    day_ago = utcnow().timestamp() - 86400

    return SystemHealth(
        status="ok" if db_ok and crypto_ok else "degraded",
        environment=settings.environment,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        database_ok=db_ok,
        database_latency_ms=round(db_ms, 2),
        crypto_ok=crypto_ok,
        crypto_selftest_ms=round(crypto_ms, 2),
        active_sessions=channel.active_sessions,
        n_users=db.query(func.count(User.id)).scalar() or 0,
        n_portfolios=db.query(func.count(Portfolio.id)).scalar() or 0,
        jobs_running=db.query(func.count(AdvisoryJob.id))
        .filter(AdvisoryJob.status == JobStatus.RUNNING)
        .scalar()
        or 0,
        jobs_failed_24h=sum(
            1
            for j in db.query(AdvisoryJob).filter(AdvisoryJob.status == JobStatus.FAILED).all()
            if j.created_at.timestamp() > day_ago
        ),
    )


@router.get("/encryption-stats", response_model=EncryptionStats)
def encryption_stats(_admin: AdminUser, db: DbSession, keystore: Keystore) -> EncryptionStats:
    """Key and ciphertext overhead.

    The interesting number is ``mean_ciphertext_kilobytes``: a CKKS ciphertext
    costs roughly the same whether it packs one value or four thousand, so a
    high mean against a low asset count means portfolios are being stored one
    ciphertext per asset somewhere, which is the packing mistake this schema
    exists to avoid.
    """
    key_stats = keystore.usage_stats(db)
    portfolios = db.query(Portfolio).all()
    total_bytes = sum(p.ciphertext_bytes for p in portfolios)
    return EncryptionStats(
        total_keys=int(key_stats["total_keys"]),
        active_keys=int(key_stats["active_keys"]),
        total_megabytes=float(key_stats["total_megabytes"]),
        mean_key_megabytes=float(key_stats["mean_key_megabytes"]),
        with_galois_keys=int(key_stats["with_galois_keys"]),
        total_portfolios=len(portfolios),
        total_ciphertext_megabytes=round(total_bytes / 1e6, 3),
        mean_ciphertext_kilobytes=round(total_bytes / len(portfolios) / 1e3, 2) if portfolios else 0.0,
    )


@router.get("/advisory-analytics", response_model=AdvisoryAnalytics)
def advisory_analytics(_admin: AdminUser, db: DbSession) -> AdvisoryAnalytics:
    """Aggregate advisory-run statistics."""
    jobs = db.query(AdvisoryJob).all()
    completed = [j for j in jobs if j.status is JobStatus.COMPLETED]
    failed = [j for j in jobs if j.status is JobStatus.FAILED]
    durations = [float(j.duration_ms) for j in completed if j.duration_ms]
    ratios = [
        float(j.run_metadata["approximation_ratio"])
        for j in completed
        if "approximation_ratio" in j.run_metadata
    ]
    return AdvisoryAnalytics(
        total_jobs=len(jobs),
        completed=len(completed),
        failed=len(failed),
        success_rate=round(len(completed) / len(jobs), 4) if jobs else 0.0,
        mean_duration_ms=round(statistics.fmean(durations), 1) if durations else None,
        median_duration_ms=round(statistics.median(durations), 1) if durations else None,
        mean_approximation_ratio=round(statistics.fmean(ratios), 4) if ratios else None,
    )


def _get_user(db, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ValidationFailed(f"no user {user_id}")
    return user


def _crypto_selftest() -> tuple[bool, float]:
    """Encrypt, evaluate and decrypt synthetic values with a throwaway keypair."""
    from ....crypto.ckks_engine import LIGHT_PARAMETERS, CKKSEngine

    started = time.perf_counter()
    try:
        engine = CKKSEngine.create_client(LIGHT_PARAMETERS)
        ct = engine.encrypt([1.5, 2.5, 3.5])
        server = CKKSEngine.from_public_context(engine.export_public_context())
        doubled = server.load_vector(ct) * 2.0
        out = engine.decrypt(CKKSEngine.dump_vector(doubled), size=3)
        ok = all(abs(a - b) < 1e-3 for a, b in zip(out, [3.0, 5.0, 7.0]))
    except Exception:
        ok = False
    return ok, (time.perf_counter() - started) * 1000
