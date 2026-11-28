"""
app/api/jobs.py — C-Level durable job inspection, cooperative cancellation & retry APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _require_clevel
from app.db.models import DocumentRecord, EvaluationRun, JobRecord
from app.db.session import get_db
from app.workers.tasks import (
    full_reindex_task,
    index_document_task,
    retry_failed_indexing_task,
    run_evaluation_task,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _serialize_job(job: JobRecord) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "target_doc_id": job.target_doc_id,
        "requested_by": job.requested_by,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "progress_message": job.progress_message,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _validate_uuid(job_id: str) -> str:
    try:
        return str(uuid.UUID(job_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@router.get("")
async def list_jobs(
    job_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(JobRecord).order_by(JobRecord.created_at.desc())
    if job_type:
        if job_type == "index":
            stmt = stmt.where(
                JobRecord.job_type.in_(["index_doc", "full_reindex", "retry_indexing"])
            )
        else:
            stmt = stmt.where(JobRecord.job_type == job_type)
    if status:
        stmt = stmt.where(JobRecord.status == status)
    stmt = stmt.offset(offset).limit(limit)
    rows = list(await db.scalars(stmt))
    return {"jobs": [_serialize_job(j) for j in rows]}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    norm_id = _validate_uuid(job_id)
    job = await db.scalar(select(JobRecord).where(JobRecord.id == norm_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _serialize_job(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    norm_id = _validate_uuid(job_id)
    job = await db.scalar(select(JobRecord).where(JobRecord.id == norm_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is already '{job.status}' and cannot be cancelled.",
        )

    now = datetime.now(timezone.utc)
    if job.status == "queued":
        job.status = "cancelled"
        job.completed_at = now
        job.progress_message = "Cancelled before worker start."
        if job.job_type == "evaluation":
            await db.execute(
                update(EvaluationRun)
                .where(EvaluationRun.job_id == job.id)
                .values(status="cancelled", error="Cancelled by administrator.", completed_at=now)
            )
    else:
        job.status = "cancel_requested"
        job.progress_message = "Cancellation requested…"

    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    norm_id = _validate_uuid(job_id)
    job = await db.scalar(select(JobRecord).where(JobRecord.id == norm_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Only failed or cancelled jobs can be retried (current: '{job.status}').",
        )

    if job.job_type == "index_doc":
        if job.target_doc_id is None:
            raise HTTPException(status_code=404, detail="Target document no longer exists.")
        doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == job.target_doc_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="Target document no longer exists.")
        doc.embedded = 0
        doc.embedded_chunks = 0
        doc.last_error = None

    new_job_id = str(uuid.uuid4())
    new_job = JobRecord(
        id=new_job_id,
        job_type=job.job_type,
        idempotency_key=job.idempotency_key,
        target_doc_id=job.target_doc_id,
        requested_by=user["username"],
        status="queued",
        progress_total=job.progress_total,
        progress_message=f"Retried from job {job.id[:8]}…",
        payload=job.payload,
    )
    eval_run: EvaluationRun | None = None
    if job.job_type == "evaluation":
        payload = job.payload or {}
        eval_run = EvaluationRun(
            id=str(uuid.uuid4()),
            job_id=new_job_id,
            mode=str(payload.get("mode", "full")),
            status="queued",
        )

    try:
        # Flush the parent job before its evaluation run (FK evaluation_runs.job_id -> jobs.id).
        db.add(new_job)
        await db.flush()
        if eval_run is not None:
            db.add(eval_run)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(
            status_code=409,
            detail="An active job with the same key is already queued or running.",
        ) from exc

    if job.job_type == "index_doc" and job.target_doc_id is not None:
        await index_document_task.kiq(new_job_id, job.target_doc_id)
    elif job.job_type == "full_reindex":
        await full_reindex_task.kiq(new_job_id)
    elif job.job_type == "retry_indexing":
        await retry_failed_indexing_task.kiq(new_job_id)
    elif job.job_type == "evaluation" and eval_run is not None:
        payload = job.payload or {}
        await run_evaluation_task.kiq(
            new_job_id,
            eval_run.id,
            str(payload.get("mode", "full")),
            payload.get("roles"),
            int(payload.get("max_per_role", 15)),
            bool(payload.get("use_builtin_dataset", False)),
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported job type '{job.job_type}'.")

    await db.refresh(new_job)
    return _serialize_job(new_job)
