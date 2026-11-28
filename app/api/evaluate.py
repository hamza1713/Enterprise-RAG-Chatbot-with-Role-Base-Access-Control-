"""
app/api/evaluate.py — Durable multi-worker Evaluation API backed by PostgreSQL + MinIO/S3.
"""

from __future__ import annotations

from io import BytesIO
import logging
import math
from typing import Literal, Optional
import uuid

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models import EvaluationRun, JobRecord
from app.db.session import get_db
from app.storage import get_storage_backend
from app.workers.tasks import _sanitize_json_numbers, run_evaluation_task

logger = logging.getLogger("FinSight.EvaluateAPI")
router = APIRouter(prefix="/evaluate", tags=["Evaluation"])


class EvaluateRequest(BaseModel):
    mode: Literal["full", "quality_only", "security_only"] = "full"
    roles: Optional[list[str]] = None
    max_per_role: int = Field(default=15, ge=1, le=100)
    use_builtin_dataset: bool = False


def _require_clevel(current_user: dict = Depends(get_current_user)):
    role = (current_user.get("role") or "").lower()
    if role != "c-level":
        raise HTTPException(
            status_code=403,
            detail="Evaluation endpoints are restricted to c-level administrators.",
        )
    return current_user


@router.post(
    "",
    summary="Trigger RAGAS evaluation",
    description=(
        "Queues a durable RAGAS quality and/or RBAC security evaluation via Taskiq. "
        "C-level role required. Poll /evaluate/status or /jobs/{job_id} for progress."
    ),
)
async def trigger_evaluation(
    request: EvaluateRequest,
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    job = JobRecord(
        id=job_id,
        job_type="evaluation",
        idempotency_key="evaluation:active",
        requested_by=user["username"],
        status="queued",
        progress_total=3 if request.mode == "full" else 2,
        progress_message=f"Queued {request.mode} evaluation",
        payload={
            "mode": request.mode,
            "roles": request.roles,
            "max_per_role": request.max_per_role,
            "use_builtin_dataset": request.use_builtin_dataset,
            "run_id": run_id,
        },
    )
    run = EvaluationRun(
        id=run_id,
        job_id=job_id,
        mode=request.mode,
        status="queued",
    )

    try:
        # Flush the parent job first: there is no relationship() between the models,
        # so a single flush could insert evaluation_runs before jobs and break its FK.
        db.add(job)
        await db.flush()
        db.add(run)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(
            status_code=409,
            detail="An evaluation is already running or queued. Check /evaluate/status.",
        ) from exc

    await run_evaluation_task.kiq(
        job_id,
        run_id,
        request.mode,
        request.roles,
        request.max_per_role,
        request.use_builtin_dataset,
    )

    return {
        "message": "Evaluation started in background.",
        "job_id": job_id,
        "run_id": run_id,
        "mode": request.mode,
        "roles": request.roles or "all",
        "status_url": "/evaluate/status",
        "report_url": "/evaluate/report",
    }


@router.get(
    "/status",
    summary="Get last evaluation status",
    response_model=None,
)
async def get_evaluation_status(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    latest = await db.scalar(
        select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(1)
    )
    if latest is None:
        return JSONResponse(content={"status": "never_run", "report_available": False})

    latest_completed = latest
    if latest.status != "completed":
        prev = await db.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.status == "completed")
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )
        if prev is not None:
            latest_completed = prev

    job_status = None
    if latest.job_id:
        job_row = await db.scalar(select(JobRecord).where(JobRecord.id == latest.job_id))
        if job_row is not None:
            job_status = job_row.status

    payload = {
        "status": latest.status,
        "job_status": job_status,
        "job_id": latest.job_id,
        "run_id": latest.id,
        "mode": latest.mode,
        "started_at": latest.started_at.isoformat() if latest.started_at else None,
        "completed_at": (
            latest.completed_at.isoformat()
            if latest.completed_at
            else (
                latest_completed.completed_at.isoformat()
                if latest_completed and latest_completed.completed_at
                else None
            )
        ),
        "overall": latest_completed.overall_scores if latest_completed else None,
        "per_role": latest_completed.per_role_scores if latest_completed else None,
        "pass_fail": latest_completed.pass_fail if latest_completed else None,
        "rbac_overall": latest_completed.rbac_overall if latest_completed else None,
        "rbac_summary": latest_completed.rbac_summary if latest_completed else None,
        "report_available": bool(latest_completed and latest_completed.report_object_key),
        "error": latest.error,
    }
    return JSONResponse(content=_sanitize_json_numbers(payload))


@router.get(
    "/report",
    summary="Download the HTML evaluation report",
    response_class=HTMLResponse,
)
async def get_evaluation_report(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    run = await db.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.status == "completed",
            EvaluationRun.report_object_key.is_not(None),
        )
        .order_by(EvaluationRun.created_at.desc())
        .limit(1)
    )
    if run is None or not run.report_object_key:
        raise HTTPException(
            status_code=404,
            detail="No report available. Run POST /evaluate first.",
        )

    storage = get_storage_backend()
    try:
        html_bytes = await storage.aget_bytes(run.report_object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evaluation report artifact missing.") from exc

    return HTMLResponse(
        content=html_bytes.decode("utf-8", errors="replace"),
        status_code=200,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/results",
    summary="Get latest RAGAS scores as JSON",
)
async def get_evaluation_results(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    run = await db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.status == "completed")
        .order_by(EvaluationRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        latest = await db.scalar(
            select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(1)
        )
        status = latest.status if latest else "never_run"
        raise HTTPException(
            status_code=404,
            detail=f"No completed evaluation. Current status: {status}",
        )

    result = {
        "run_id": run.id,
        "job_id": run.job_id,
        "ragas_scores": run.overall_scores,
        "per_role": run.per_role_scores,
        "pass_fail": run.pass_fail,
        "rbac_status": run.rbac_overall,
        "rbac_summary": run.rbac_summary,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    return JSONResponse(content=_sanitize_json_numbers(result))


@router.get(
    "/records",
    summary="Get detailed RAGAS evaluation records",
)
async def get_evaluation_records(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    run = await db.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.status == "completed",
            EvaluationRun.records_object_key.is_not(None),
        )
        .order_by(EvaluationRun.created_at.desc())
        .limit(1)
    )
    if run is None or not run.records_object_key:
        raise HTTPException(
            status_code=404,
            detail="No evaluation records found. Run an evaluation first.",
        )

    storage = get_storage_backend()
    try:
        csv_bytes = await storage.aget_bytes(run.records_object_key)
        df = pd.read_csv(BytesIO(csv_bytes))
        records = df.to_dict(orient="records")
        for rec in records:
            for k, v in rec.items():
                if isinstance(v, float) and math.isnan(v):
                    rec[k] = None
        return JSONResponse(content={"records": _sanitize_json_numbers(records)})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evaluation records artifact missing.") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load evaluation records: {exc}",
        ) from exc
