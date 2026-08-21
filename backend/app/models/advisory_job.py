"""Advisory pipeline runs.

A full run -- Planning, Risk, Execution, QAOA -- takes minutes, so the API
starts a job and the client polls. This table is that job's record, and it is
also the audit trail for what the agents did.

The ``result_ciphertext`` column holds the recommendation *encrypted under the
user's key*. The server writes it and can never read it back.
"""

from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UTCDateTime, UUIDPrimaryKey

if TYPE_CHECKING:
    from .user import User


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(str, enum.Enum):
    """Which agent currently owns the job. Drives the progress bar."""

    QUEUED = "queued"
    PLANNING = "planning"
    RISK = "risk"
    QUBO = "qubo"
    OPTIMIZATION = "optimization"
    EXECUTION = "execution"
    DONE = "done"


class AdvisoryJob(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "advisory_jobs"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    portfolio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    #: Set when this job refines an earlier recommendation.
    parent_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("advisory_jobs.id", ondelete="SET NULL")
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=16),
        default=JobStatus.PENDING,
        nullable=False,
        index=True,
    )
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, native_enum=False, length=16), default=JobStage.QUEUED, nullable=False
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    goals_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    #: The recommendation, encrypted under the user's public key.
    result_ciphertext: Mapped[str | None] = mapped_column(Text)
    #: Non-sensitive run metadata: circuit depth, iterations, timings.
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="advisory_jobs")

    # -- JSON convenience ---------------------------------------------------
    @property
    def goals(self) -> dict[str, Any]:
        return json.loads(self.goals_json)

    @goals.setter
    def goals(self, value: dict[str, Any]) -> None:
        self.goals_json = json.dumps(value)

    @property
    def constraints(self) -> dict[str, Any]:
        return json.loads(self.constraints_json)

    @constraints.setter
    def constraints(self, value: dict[str, Any]) -> None:
        self.constraints_json = json.dumps(value)

    @property
    def run_metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_json)

    @run_metadata.setter
    def run_metadata(self, value: dict[str, Any]) -> None:
        self.metadata_json = json.dumps(value)

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    def __repr__(self) -> str:
        return f"<AdvisoryJob {self.id} {self.status.value}/{self.stage.value} {self.progress:.0%}>"
