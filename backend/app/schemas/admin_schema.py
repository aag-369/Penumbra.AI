"""Admin dashboard models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class AdminUserOut(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    last_activity_at: datetime | None
    is_locked: bool
    n_portfolios: int
    n_advisory_jobs: int
    n_keys: int


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action: str
    severity: str
    actor_user_id: str | None
    target_user_id: str | None
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    details: dict
    created_at: datetime

    @field_validator("action", "severity", mode="before")
    @classmethod
    def _enum_value(cls, v: object) -> object:
        return getattr(v, "value", v)


class SystemHealth(BaseModel):
    status: str
    environment: str
    uptime_seconds: float
    database_ok: bool
    database_latency_ms: float
    crypto_ok: bool
    crypto_selftest_ms: float
    active_sessions: int
    n_users: int
    n_portfolios: int
    jobs_running: int
    jobs_failed_24h: int


class EncryptionStats(BaseModel):
    """Ciphertext and key overhead, for the admin dashboard."""

    total_keys: int
    active_keys: int
    total_megabytes: float
    mean_key_megabytes: float
    with_galois_keys: int
    total_portfolios: int
    total_ciphertext_megabytes: float
    mean_ciphertext_kilobytes: float


class AdvisoryAnalytics(BaseModel):
    total_jobs: int
    completed: int
    failed: int
    success_rate: float
    mean_duration_ms: float | None
    median_duration_ms: float | None
    mean_approximation_ratio: float | None
