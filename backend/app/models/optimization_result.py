"""QUBO / QAOA run records, kept for benchmarking and for the viva write-up.

Nothing here identifies an allocation. The allocation itself is encrypted on
:class:`~app.models.advisory_job.AdvisoryJob`; this table stores solver
telemetry -- depth, iterations, objective values, wall time -- so QAOA can be
compared against the classical baseline over many runs.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import Timestamped, UUIDPrimaryKey


class OptimizationResult(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "optimization_results"

    advisory_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("advisory_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # -- problem ------------------------------------------------------------
    n_assets: Mapped[int] = mapped_column(Integer, nullable=False)
    n_qubits: Mapped[int] = mapped_column(Integer, nullable=False)
    n_bits_per_asset: Mapped[int] = mapped_column(Integer, nullable=False)
    qubo_density: Mapped[float | None] = mapped_column(Float)
    was_obfuscated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Objective value of the recovered solution divided by that of the same
    #: solution on the unobfuscated problem. 1.0 means obfuscation was lossless.
    reconstruction_fidelity: Mapped[float | None] = mapped_column(Float)

    # -- QAOA ---------------------------------------------------------------
    solver: Mapped[str] = mapped_column(String(32), default="qaoa", nullable=False)
    qaoa_layers: Mapped[int | None] = mapped_column(Integer)
    circuit_depth: Mapped[int | None] = mapped_column(Integer)
    iterations: Mapped[int | None] = mapped_column(Integer)
    shots: Mapped[int | None] = mapped_column(Integer)
    qaoa_objective: Mapped[float | None] = mapped_column(Float)
    qaoa_runtime_ms: Mapped[int | None] = mapped_column(Integer)

    # -- classical baseline -------------------------------------------------
    classical_objective: Mapped[float | None] = mapped_column(Float)
    classical_runtime_ms: Mapped[int | None] = mapped_column(Integer)
    #: QAOA objective over classical objective. Below 1.0 means QAOA lost.
    approximation_ratio: Mapped[float | None] = mapped_column(Float)

    extra_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    @property
    def extra(self) -> dict[str, Any]:
        return json.loads(self.extra_json)

    @extra.setter
    def extra(self, value: dict[str, Any]) -> None:
        self.extra_json = json.dumps(value)

    def __repr__(self) -> str:
        return (
            f"<OptimizationResult qubits={self.n_qubits} solver={self.solver} "
            f"ratio={self.approximation_ratio}>"
        )
