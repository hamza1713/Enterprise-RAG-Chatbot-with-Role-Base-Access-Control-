"""
app/workers/tasks.py — Durable PostgreSQL-backed Taskiq background tasks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
import logging
import math
from pathlib import Path
import tempfile
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.cache import cache_manager
from app.core.config import EVAL_OUTPUT_DIR
from app.db.models import DocumentRecord, EvaluationRun, JobRecord
from app.db.session import async_session
from app.rag.errors import classify_api_error, parse_retry_delay
from app.storage import get_storage_backend
from app.workers.broker import broker

logger = logging.getLogger("FinSight.workers.tasks")


class JobCancelledError(Exception):
    """Raised cleanly when a worker detects cancel_requested/cancelled in Postgres."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_json_numbers(obj: Any) -> Any:
    """Recursively convert NaN/Inf floats and pandas NA values to None for strict JSONB."""
    if isinstance(obj, dict):
        return {k: _sanitize_json_numbers(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_numbers(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return _sanitize_json_numbers(obj.item())
        except Exception:
            pass
    return obj


def invalidate_role_cache(role: str) -> None:
    """Clear role-scoped Redis/memory query caches after document mutations."""
    clean_role = (role or "general").strip().lower()
    cache_manager.delete_prefix(f"finsight:cache:{clean_role}:")
    cache_manager.delete_prefix("finsight:cache:c-level:")
    if clean_role == "general":
        cache_manager.clear()


async def ensure_job_not_cancelled(job_id: str) -> None:
    """Check Postgres job state and transition cancel_requested -> cancelled cleanly."""
    async with async_session() as db:
        job = await db.scalar(select(JobRecord).where(JobRecord.id == job_id))
        if job is None:
            return
        if job.status in ("cancel_requested", "cancelled"):
            if job.status != "cancelled":
                job.status = "cancelled"
                job.completed_at = _utc_now()
                job.progress_message = "Cancelled by administrator."
                await db.commit()
            raise JobCancelledError(f"Job {job_id} cancelled")


async def update_job_progress(
    job_id: str,
    current: int,
    total: int,
    message: str,
) -> None:
    async with async_session() as db:
        await db.execute(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(
                progress_current=current,
                progress_total=total,
                progress_message=message,
            )
        )
        await db.commit()


async def _mark_job_running(job_id: str, message: str = "Starting…") -> JobRecord | None:
    async with async_session() as db:
        job = await db.scalar(select(JobRecord).where(JobRecord.id == job_id))
        if job is None:
            return None
        if job.status in ("cancel_requested", "cancelled"):
            job.status = "cancelled"
            job.completed_at = job.completed_at or _utc_now()
            job.progress_message = "Cancelled before execution."
            await db.commit()
            raise JobCancelledError(f"Job {job_id} cancelled")
        job.status = "running"
        job.started_at = job.started_at or _utc_now()
        job.completed_at = None
        job.error = None
        job.attempts = (job.attempts or 0) + 1
        job.progress_message = message
        await db.commit()
        return job


async def _mark_job_completed(job_id: str, result: dict, message: str = "Completed") -> None:
    async with async_session() as db:
        job = await db.scalar(select(JobRecord).where(JobRecord.id == job_id))
        if job is None:
            return
        if job.status in ("cancel_requested", "cancelled"):
            job.status = "cancelled"
            job.completed_at = job.completed_at or _utc_now()
            job.progress_message = "Cancelled."
        else:
            job.status = "completed"
            job.completed_at = _utc_now()
            job.result = _sanitize_json_numbers(result)
            job.progress_current = job.progress_total or 1
            job.progress_total = job.progress_total or 1
            job.progress_message = message
            job.error = None
        await db.commit()


async def _mark_job_failed(job_id: str, error_msg: str) -> None:
    async with async_session() as db:
        await db.execute(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(
                status="failed",
                error=error_msg[:4000],
                completed_at=_utc_now(),
                progress_message="Failed",
            )
        )
        await db.commit()


async def _mark_doc_failed(doc_id: int, error_msg: str) -> None:
    async with async_session() as db:
        await db.execute(
            update(DocumentRecord)
            .where(DocumentRecord.id == doc_id)
            .values(embedded=-1, last_error=error_msg[:4000])
        )
        await db.commit()


# ════════════════════════════════════════════════════════════════════════════════
#  TASKIQ WORKER TASKS
# ════════════════════════════════════════════════════════════════════════════════


@broker.task
async def index_document_task(job_id: str, doc_id: int) -> dict:
    """Index or reindex a single DocumentRecord with retry backoff and cancellation."""
    from app.rag.module import ingest_single_document

    try:
        job = await _mark_job_running(job_id, f"Indexing document {doc_id}…")
        if job is None:
            return {"status": "missing_job"}

        async def _progress(cur: int, tot: int, msg: str) -> None:
            await update_job_progress(job_id, cur, tot, msg)

        while True:
            try:
                summary = await ingest_single_document(
                    doc_id,
                    cancel_check=lambda: ensure_job_not_cancelled(job_id),
                    progress_callback=_progress,
                )
                invalidate_role_cache(summary["role"])
                await _mark_job_completed(job_id, summary, "Indexed successfully.")
                return summary
            except JobCancelledError:
                raise
            except Exception as exc:
                kind = classify_api_error(exc)
                async with async_session() as db:
                    cur_job = await db.scalar(select(JobRecord).where(JobRecord.id == job_id))
                    attempts = cur_job.attempts if cur_job else 1
                    max_attempts = cur_job.max_attempts if cur_job else 3
                    can_retry = kind == "transient_rate_limit" and attempts < max_attempts
                    if can_retry and cur_job is not None:
                        cur_job.attempts = attempts + 1
                        cur_job.progress_message = f"Rate limited — retrying (attempt {attempts + 1}/{max_attempts})…"
                        await db.commit()
                if kind == "transient_rate_limit" and can_retry:
                    wait = min(parse_retry_delay(exc, 5.0 * attempts), 60.0)
                    await asyncio.sleep(wait)
                    await ensure_job_not_cancelled(job_id)
                    continue
                raise

    except JobCancelledError:
        logger.info(f"[Worker] index_document_task cancelled cleanly: job={job_id} doc={doc_id}")
        return {"status": "cancelled", "doc_id": doc_id}
    except Exception as exc:
        logger.error(f"[Worker] index_document_task failed: job={job_id} doc={doc_id}: {exc}")
        await _mark_doc_failed(doc_id, str(exc))
        await _mark_job_failed(job_id, str(exc))
        return {"status": "failed", "doc_id": doc_id, "error": str(exc)}


@broker.task
async def full_reindex_task(job_id: str) -> dict:
    """Non-destructive full reindex across all registered documents."""
    from app.rag.module import ingest_single_document

    try:
        job = await _mark_job_running(job_id, "Scanning documents for full reindex…")
        if job is None:
            return {"status": "missing_job"}

        async with async_session() as db:
            doc_ids = list(
                await db.scalars(select(DocumentRecord.id).order_by(DocumentRecord.id.asc()))
            )

        total = len(doc_ids)
        indexed = 0
        failed = 0
        await update_job_progress(job_id, 0, total, f"Reindexing {total} documents…")

        for idx, doc_id in enumerate(doc_ids, start=1):
            await ensure_job_not_cancelled(job_id)
            try:
                await ingest_single_document(
                    doc_id,
                    cancel_check=lambda: ensure_job_not_cancelled(job_id),
                )
                indexed += 1
            except JobCancelledError:
                raise
            except Exception as exc:
                failed += 1
                await _mark_doc_failed(doc_id, str(exc))
                if classify_api_error(exc) == "hard_quota":
                    await _mark_job_failed(job_id, f"Stopped on hard quota: {exc}")
                    return {"status": "failed", "indexed": indexed, "failed": failed, "total": total}
            await update_job_progress(
                job_id, idx, total, f"Processed {idx}/{total} documents ({failed} failed)"
            )

        cache_manager.clear()
        summary = {"indexed": indexed, "failed": failed, "total": total}
        await _mark_job_completed(job_id, summary, f"Reindexed {indexed}/{total} documents.")
        return summary

    except JobCancelledError:
        return {"status": "cancelled"}
    except Exception as exc:
        await _mark_job_failed(job_id, str(exc))
        return {"status": "failed", "error": str(exc)}


@broker.task
async def retry_failed_indexing_task(job_id: str) -> dict:
    """Retry only failed or pending documents (embedded IN (-1, 0))."""
    from app.rag.module import ingest_single_document

    try:
        job = await _mark_job_running(job_id, "Finding failed/pending documents…")
        if job is None:
            return {"status": "missing_job"}

        async with async_session() as db:
            doc_ids = list(
                await db.scalars(
                    select(DocumentRecord.id)
                    .where(DocumentRecord.embedded.in_([-1, 0]))
                    .order_by(DocumentRecord.id.asc())
                )
            )
            if doc_ids:
                await db.execute(
                    update(DocumentRecord)
                    .where(DocumentRecord.id.in_(doc_ids))
                    .values(embedded=0, last_error=None)
                )
                await db.commit()

        total = len(doc_ids)
        indexed = 0
        failed = 0
        await update_job_progress(job_id, 0, total, f"Retrying {total} pending/failed documents…")

        for idx, doc_id in enumerate(doc_ids, start=1):
            await ensure_job_not_cancelled(job_id)
            try:
                summary = await ingest_single_document(
                    doc_id,
                    cancel_check=lambda: ensure_job_not_cancelled(job_id),
                )
                invalidate_role_cache(summary["role"])
                indexed += 1
            except JobCancelledError:
                raise
            except Exception as exc:
                failed += 1
                await _mark_doc_failed(doc_id, str(exc))
                if classify_api_error(exc) == "hard_quota":
                    await _mark_job_failed(job_id, f"Stopped on hard quota: {exc}")
                    return {"status": "failed", "indexed": indexed, "failed": failed, "total": total}
            await update_job_progress(
                job_id, idx, total, f"Retried {idx}/{total} documents ({failed} failed)"
            )

        summary = {"indexed": indexed, "failed": failed, "total": total}
        await _mark_job_completed(job_id, summary, f"Retried {indexed}/{total} documents.")
        return summary

    except JobCancelledError:
        return {"status": "cancelled"}
    except Exception as exc:
        await _mark_job_failed(job_id, str(exc))
        return {"status": "failed", "error": str(exc)}


@broker.task
async def run_evaluation_task(
    job_id: str,
    run_id: str,
    mode: str,
    roles: list[str] | None,
    max_per_role: int,
    use_builtin: bool,
) -> dict:
    """Durable RAGAS quality + RBAC security evaluation backed by Postgres & MinIO/S3."""
    started_at = _utc_now()
    try:
        job = await _mark_job_running(job_id, f"Running {mode} evaluation…")
        if job is None:
            return {"status": "missing_job"}

        async with async_session() as db:
            await db.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values(status="running", started_at=started_at, error=None)
            )
            await db.commit()

        ragas_results = None
        security_report = None
        total_steps = 3 if mode == "full" else 2
        step = 0

        if mode in ("full", "quality_only"):
            await ensure_job_not_cancelled(job_id)
            step += 1
            await update_job_progress(job_id, step, total_steps, "Running RAGAS quality metrics…")
            from app.rag_evaluator.ragas_evaluator import (
                evaluate_from_builtin,
                evaluate_from_csv,
            )

            if use_builtin:
                ragas_results = await asyncio.to_thread(
                    evaluate_from_builtin,
                    roles=roles,
                    output_csv="evaluation_results_ragas.csv",
                )
            else:
                ragas_results = await asyncio.to_thread(
                    evaluate_from_csv,
                    roles=roles,
                    max_per_role=max_per_role,
                    output_csv="evaluation_results_ragas.csv",
                )

        if mode in ("full", "security_only"):
            await ensure_job_not_cancelled(job_id)
            step += 1
            await update_job_progress(job_id, step, total_steps, "Running RBAC security suite…")
            from app.rag_evaluator.rbac_security_eval import run_all_security_tests

            security_report = await asyncio.to_thread(
                run_all_security_tests,
                output_json="rbac_security_report.json",
                skip_ragas_test=(mode == "security_only"),
            )

        await ensure_job_not_cancelled(job_id)
        step += 1
        await update_job_progress(job_id, step, total_steps, "Generating & storing report artifacts…")

        storage = get_storage_backend()
        report_key: str | None = None
        records_key: str | None = None

        from app.rag_evaluator.eval_report import generate_html_report

        with tempfile.TemporaryDirectory(prefix="finsight-eval-") as tmpdir:
            report_path = Path(tmpdir) / "ragas_report.html"
            await asyncio.to_thread(
                generate_html_report,
                ragas_results=ragas_results,
                security_report=security_report,
                output_path=str(report_path),
            )
            if report_path.is_file():
                report_key = await storage.aput_bytes(
                    f"evaluations/{run_id}/ragas_report.html",
                    report_path.read_bytes(),
                    content_type="text/html; charset=utf-8",
                )

        if ragas_results:
            csv_candidate = Path(ragas_results.get("csv_path") or (EVAL_OUTPUT_DIR / "evaluation_results_ragas.csv"))
            if csv_candidate.is_file():
                records_key = await storage.aput_bytes(
                    f"evaluations/{run_id}/evaluation_results_ragas.csv",
                    csv_candidate.read_bytes(),
                    content_type="text/csv; charset=utf-8",
                )

        completed_at = _utc_now()
        clean_overall = _sanitize_json_numbers(ragas_results.get("overall") if ragas_results else None)
        clean_per_role = _sanitize_json_numbers(ragas_results.get("per_role") if ragas_results else None)
        clean_pass_fail = _sanitize_json_numbers(ragas_results.get("pass_fail") if ragas_results else None)
        rbac_overall = security_report.get("overall_status") if security_report else None
        rbac_summary = _sanitize_json_numbers(security_report.get("summary") if security_report else None)

        async with async_session() as db:
            await db.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values(
                    status="completed",
                    overall_scores=clean_overall,
                    per_role_scores=clean_per_role,
                    pass_fail=clean_pass_fail,
                    rbac_overall=rbac_overall,
                    rbac_summary=rbac_summary,
                    report_object_key=report_key,
                    records_object_key=records_key,
                    error=None,
                    completed_at=completed_at,
                )
            )
            await db.commit()

        result_payload = {
            "run_id": run_id,
            "mode": mode,
            "rbac_overall": rbac_overall,
            "report_object_key": report_key,
        }
        await _mark_job_completed(job_id, result_payload, "Evaluation completed.")
        return result_payload

    except JobCancelledError:
        async with async_session() as db:
            await db.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values(
                    status="cancelled",
                    error="Cancelled by administrator.",
                    completed_at=_utc_now(),
                )
            )
            await db.commit()
        return {"status": "cancelled", "run_id": run_id}

    except Exception as exc:
        logger.error(f"[Worker] run_evaluation_task failed: job={job_id} run={run_id}: {exc}", exc_info=True)
        async with async_session() as db:
            await db.execute(
                update(EvaluationRun)
                .where(EvaluationRun.id == run_id)
                .values(
                    status="failed",
                    error=str(exc)[:4000],
                    completed_at=_utc_now(),
                )
            )
            await db.commit()
        await _mark_job_failed(job_id, str(exc))
        return {"status": "failed", "run_id": run_id, "error": str(exc)}


# ════════════════════════════════════════════════════════════════════════════════
#  IDEMPOTENT JOB DISPATCH HELPERS (called by API & startup seeding)
# ════════════════════════════════════════════════════════════════════════════════


async def enqueue_document_index_job(
    doc_id: int,
    requested_by: str | None = None,
) -> tuple[str, bool]:
    """
    Create or reuse an active durable job for doc_id and dispatch via Taskiq.
    Returns (job_id, newly_created).
    """
    idem_key = f"index_doc:{doc_id}"
    job_id = str(uuid.uuid4())
    newly_created = False

    async with async_session() as db:
        doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
        if doc is None:
            raise ValueError(f"Document {doc_id} not found")
        job = JobRecord(
            id=job_id,
            job_type="index_doc",
            idempotency_key=idem_key,
            target_doc_id=doc_id,
            requested_by=requested_by,
            status="queued",
            progress_total=4,
            progress_message=f"Queued '{doc.filename}'",
            payload={"doc_id": doc_id, "filename": doc.filename, "role": doc.role},
        )
        db.add(job)
        try:
            await db.commit()
            newly_created = True
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key == idem_key,
                    JobRecord.status.in_(["queued", "running", "cancel_requested"]),
                )
            )
            if existing is not None:
                return existing.id, False
            raise

    await index_document_task.kiq(job_id, doc_id)
    return job_id, newly_created


async def enqueue_pending_documents(requested_by: str | None = "system") -> list[str]:
    """Ensure every unembedded document has an active durable indexing job queued."""
    async with async_session() as db:
        pending_ids = list(
            await db.scalars(
                select(DocumentRecord.id)
                .where(DocumentRecord.embedded == 0)
                .order_by(DocumentRecord.id.asc())
            )
        )
    job_ids: list[str] = []
    for doc_id in pending_ids:
        job_id, _ = await enqueue_document_index_job(doc_id, requested_by=requested_by)
        job_ids.append(job_id)
    return job_ids


async def enqueue_full_reindex_job(requested_by: str | None = None) -> tuple[str, int]:
    """Create or reuse an active full_reindex durable job and enqueue it via Taskiq."""
    idem_key = "full_reindex:active"
    job_id = str(uuid.uuid4())
    async with async_session() as db:
        from sqlalchemy import func as sa_func

        total = int(await db.scalar(select(sa_func.count()).select_from(DocumentRecord)) or 0)
        await db.execute(update(DocumentRecord).values(embedded=0, embedded_chunks=0, last_error=None))
        job = JobRecord(
            id=job_id,
            job_type="full_reindex",
            idempotency_key=idem_key,
            requested_by=requested_by,
            status="queued",
            progress_total=total,
            progress_message=f"Queued full reindex ({total} documents)",
            payload={"queued_docs": total},
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key == idem_key,
                    JobRecord.status.in_(["queued", "running", "cancel_requested"]),
                )
            )
            if existing is not None:
                return existing.id, total
            raise

    await full_reindex_task.kiq(job_id)
    return job_id, total


async def enqueue_retry_failed_job(requested_by: str | None = None) -> tuple[str, int]:
    """Create or reuse an active retry_indexing durable job and enqueue it via Taskiq."""
    from sqlalchemy import func as sa_func

    idem_key = "retry_indexing:active"
    job_id = str(uuid.uuid4())
    async with async_session() as db:
        total = int(
            await db.scalar(
                select(sa_func.count())
                .select_from(DocumentRecord)
                .where(DocumentRecord.embedded.in_([-1, 0]))
            )
            or 0
        )
        await db.execute(
            update(DocumentRecord)
            .where(DocumentRecord.embedded == -1)
            .values(embedded=0, embedded_chunks=0, last_error=None)
        )
        job = JobRecord(
            id=job_id,
            job_type="retry_indexing",
            idempotency_key=idem_key,
            requested_by=requested_by,
            status="queued",
            progress_total=total,
            progress_message=f"Queued retry for {total} documents",
            payload={"queued_docs": total},
        )
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(
                select(JobRecord).where(
                    JobRecord.idempotency_key == idem_key,
                    JobRecord.status.in_(["queued", "running", "cancel_requested"]),
                )
            )
            if existing is not None:
                return existing.id, total
            raise

    await retry_failed_indexing_task.kiq(job_id)
    return job_id, total
