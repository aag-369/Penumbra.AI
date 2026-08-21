"""Optimisation telemetry.

Separate from ``/advisor`` because the audience is different: these endpoints
serve the benchmark write-up, not the end user. Nothing here reveals an
allocation -- the rows record solver behaviour, not solutions.
"""

from __future__ import annotations

import statistics

from fastapi import APIRouter

from ....models.advisory_job import AdvisoryJob
from ....models.optimization_result import OptimizationResult
from ....services.portfolio_service import ValidationFailed
from ..dependencies import CurrentUser, DbSession

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=list[dict])
def results_for_job(job_id: str, current_user: CurrentUser, db: DbSession) -> list[dict]:
    """Solver telemetry for one advisory run."""
    job = (
        db.query(AdvisoryJob)
        .filter(AdvisoryJob.id == job_id, AdvisoryJob.user_id == current_user.id)
        .one_or_none()
    )
    if job is None:
        raise ValidationFailed(f"no advisory job {job_id} for this account")
    rows = (
        db.query(OptimizationResult)
        .filter(OptimizationResult.advisory_job_id == job.id)
        .order_by(OptimizationResult.created_at)
        .all()
    )
    return [_serialise(r) for r in rows]


@router.get("/benchmarks", response_model=dict)
def benchmark_summary(current_user: CurrentUser, db: DbSession) -> dict:
    """QAOA against the classical baseline, aggregated over this user's runs.

    Reported without editorialising. If ``mean_approximation_ratio`` is below
    1.0, QAOA lost, and that is the result -- at these problem sizes a
    branch-and-bound solver finding the exact optimum in milliseconds is the
    expected outcome, not a failure of the implementation.
    """
    rows = (
        db.query(OptimizationResult)
        .join(AdvisoryJob, OptimizationResult.advisory_job_id == AdvisoryJob.id)
        .filter(AdvisoryJob.user_id == current_user.id)
        .all()
    )
    if not rows:
        return {"n_runs": 0, "note": "no optimisation runs recorded yet"}

    ratios = [r.approximation_ratio for r in rows if r.approximation_ratio is not None]
    qaoa_ms = [r.qaoa_runtime_ms for r in rows if r.qaoa_runtime_ms is not None]
    classical_ms = [r.classical_runtime_ms for r in rows if r.classical_runtime_ms is not None]
    fidelities = [r.reconstruction_fidelity for r in rows if r.reconstruction_fidelity is not None]

    return {
        "n_runs": len(rows),
        "mean_approximation_ratio": _mean(ratios),
        "median_approximation_ratio": _median(ratios),
        "qaoa_wins": sum(1 for r in ratios if r > 1.0),
        "mean_qaoa_runtime_ms": _mean(qaoa_ms),
        "mean_classical_runtime_ms": _mean(classical_ms),
        "mean_reconstruction_fidelity": _mean(fidelities),
        "mean_qubits": _mean([float(r.n_qubits) for r in rows]),
        "obfuscated_runs": sum(1 for r in rows if r.was_obfuscated),
    }


def _serialise(row: OptimizationResult) -> dict:
    return {
        "id": row.id,
        "n_assets": row.n_assets,
        "n_qubits": row.n_qubits,
        "n_bits_per_asset": row.n_bits_per_asset,
        "qubo_density": row.qubo_density,
        "was_obfuscated": row.was_obfuscated,
        "reconstruction_fidelity": row.reconstruction_fidelity,
        "solver": row.solver,
        "qaoa_layers": row.qaoa_layers,
        "circuit_depth": row.circuit_depth,
        "iterations": row.iterations,
        "shots": row.shots,
        "qaoa_objective": row.qaoa_objective,
        "qaoa_runtime_ms": row.qaoa_runtime_ms,
        "classical_objective": row.classical_objective,
        "classical_runtime_ms": row.classical_runtime_ms,
        "approximation_ratio": row.approximation_ratio,
        "extra": row.extra,
        "created_at": row.created_at.isoformat(),
    }


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None
