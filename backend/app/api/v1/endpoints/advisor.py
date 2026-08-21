"""Advisory pipeline: start a run, poll it, refine it.

A run takes minutes -- QAOA simulation dominates -- so the API is asynchronous.
``POST /generate`` creates a job row and returns immediately; the client polls
``GET /jobs/{id}`` until the status is terminal.

The agent pipeline itself is Phase 2/4 and raises :class:`NotImplementedError`,
which the exception handlers turn into ``501 Not Implemented``. Everything
around it -- job creation, ownership checks, stage tracking, auditing,
persistence of the encrypted result -- is implemented and tested, so the
remaining work is to fill in the agents rather than to build the machinery.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, status

from ....database import SessionLocal
from ....models.advisory_job import AdvisoryJob, JobStage, JobStatus
from ....models.audit_log import AuditAction, AuditSeverity
from ....models.base import utcnow
from ....schemas.advisor_schema import (
    AdvisoryJobOut,
    AdvisoryRequest,
    AdvisoryResultOut,
    RefinementRequest,
)
from ....schemas.common import Message
from ....services.audit_service import AuditService
from ....services.portfolio_service import PortfolioService, ValidationFailed
from ..dependencies import CurrentUser, DbSession, Req

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=AdvisoryJobOut, status_code=status.HTTP_202_ACCEPTED)
def generate_recommendation(
    payload: AdvisoryRequest,
    current_user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
    request: Req,
) -> AdvisoryJob:
    """Queue an advisory run over the caller's encrypted portfolio."""
    portfolio = (
        PortfolioService.get(db, current_user.id, payload.portfolio_id)
        if payload.portfolio_id
        else PortfolioService.current(db, current_user.id)
    )

    job = AdvisoryJob(user_id=current_user.id, portfolio_id=portfolio.id)
    job.goals = payload.goals.model_dump()
    db.add(job)
    db.flush()

    AuditService.record(
        db,
        AuditAction.ADVISORY_STARTED,
        actor_user_id=current_user.id,
        resource_type="advisory_job",
        resource_id=job.id,
        request=request,
        portfolio_id=portfolio.id,
        n_assets=portfolio.n_assets,
        risk_tolerance=payload.goals.risk_tolerance,
    )
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_pipeline, job.id)
    return job


@router.post("/jobs/{job_id}/refine", response_model=AdvisoryJobOut, status_code=status.HTTP_202_ACCEPTED)
def refine_recommendation(
    job_id: str,
    payload: RefinementRequest,
    current_user: CurrentUser,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> AdvisoryJob:
    """Queue a follow-up run that adjusts an existing recommendation."""
    parent = _owned_job(db, current_user.id, job_id)
    if parent.status is not JobStatus.COMPLETED:
        raise ValidationFailed(
            f"job {job_id} is {parent.status.value}; only a completed run can be refined"
        )

    child = AdvisoryJob(
        user_id=current_user.id, portfolio_id=parent.portfolio_id, parent_job_id=parent.id
    )
    child.goals = (payload.goals.model_dump() if payload.goals else parent.goals) | {
        "refinement_instruction": payload.instruction
    }
    db.add(child)
    db.commit()
    db.refresh(child)

    background_tasks.add_task(_run_pipeline, child.id)
    return child


@router.get("/jobs", response_model=list[AdvisoryJobOut])
def list_jobs(current_user: CurrentUser, db: DbSession, limit: int = 50) -> list[AdvisoryJob]:
    """This user's advisory runs, newest first."""
    return (
        db.query(AdvisoryJob)
        .filter(AdvisoryJob.user_id == current_user.id)
        .order_by(AdvisoryJob.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )


@router.get("/jobs/{job_id}", response_model=AdvisoryResultOut)
def get_job(job_id: str, current_user: CurrentUser, db: DbSession):
    """Poll a run.

    When complete, ``recommendation_ciphertext`` holds the advice encrypted
    under the caller's key. The server wrote it and cannot read it back; only
    the browser, holding the secret key, can.
    """
    job = _owned_job(db, current_user.id, job_id)
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "portfolio_id": job.portfolio_id,
        "parent_job_id": job.parent_job_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_ms": job.duration_ms,
        "error_message": job.error_message,
        "recommendation_ciphertext": job.result_ciphertext,
        "run_metadata": job.run_metadata,
    }


@router.delete("/jobs/{job_id}", response_model=Message)
def cancel_job(job_id: str, current_user: CurrentUser, db: DbSession) -> Message:
    """Cancel a run that has not finished."""
    job = _owned_job(db, current_user.id, job_id)
    if job.is_terminal:
        raise ValidationFailed(f"job {job_id} already finished as {job.status.value}")
    job.status = JobStatus.CANCELLED
    job.finished_at = utcnow()
    db.commit()
    return Message(message=f"job {job_id} cancelled")


def _owned_job(db, user_id: str, job_id: str) -> AdvisoryJob:
    """Fetch a job, scoped to its owner.

    Scoping on ``user_id`` in the query rather than fetching and then comparing
    means an unauthorised id returns 404 rather than 403, so the endpoint is not
    an existence oracle for other users' job ids.
    """
    job = (
        db.query(AdvisoryJob)
        .filter(AdvisoryJob.id == job_id, AdvisoryJob.user_id == user_id)
        .one_or_none()
    )
    if job is None:
        raise ValidationFailed(f"no advisory job {job_id} for this account")
    return job


def _run_pipeline(job_id: str) -> None:
    """Background worker for one advisory run.

    Opens its own session: the request-scoped one is closed by the time this
    runs. Any failure is recorded on the job row and audited, so a crashed run
    leaves a diagnosable record instead of a job stuck at "pending".

    ``BackgroundTasks`` is in-process and does not survive a restart. Phase 5
    should move this to Celery or arq with the same contract.
    """
    db = SessionLocal()
    try:
        job = db.get(AdvisoryJob, job_id)
        if job is None or job.status is JobStatus.CANCELLED:
            return

        job.status = JobStatus.RUNNING
        job.stage = JobStage.PLANNING
        job.started_at = utcnow()
        db.commit()

        # Phase 2/4: build the orchestrator, run it, encrypt the result under
        # the user's public engine, and store it on job.result_ciphertext.
        from ....agents.orchestrator import build_default_orchestrator

        build_default_orchestrator()
        raise NotImplementedError("advisory pipeline is Phase 2/4")

    except Exception as exc:
        db.rollback()
        job = db.get(AdvisoryJob, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.stage = JobStage.QUEUED
            job.finished_at = utcnow()
            job.error_message = f"{type(exc).__name__}: {exc}"
            if job.started_at:
                job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
            AuditService.record(
                db,
                AuditAction.ADVISORY_FAILED,
                actor_user_id=job.user_id,
                resource_type="advisory_job",
                resource_id=job.id,
                severity=AuditSeverity.WARNING,
                reason=type(exc).__name__,
            )
            db.commit()
        logger.warning("advisory job %s failed: %s", job_id, exc)
    finally:
        db.close()
