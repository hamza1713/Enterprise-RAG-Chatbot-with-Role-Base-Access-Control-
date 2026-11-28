"""
app/api/audit.py — C-Level Audit & Observability governance query and export endpoints.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _require_clevel
from app.core.audit import sanitize_csv_cell
from app.db.models import AuditLog
from app.db.session import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _escape_like(term: str) -> str:
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _serialize_audit(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_id": row.event_id,
        "request_id": row.request_id,
        "thread_id": row.thread_id,
        "username": row.username,
        "user_role": row.user_role,
        "auth_provider": row.auth_provider,
        "event_type": row.event_type,
        "mode": row.mode,
        "model_name": row.model_name,
        "authorized_doc_count": row.authorized_doc_count,
        "authorized_dataset_names": list(row.authorized_dataset_names or []),
        "cited_doc_ids": list(row.cited_doc_ids or []),
        "cited_chunk_ids": list(row.cited_chunk_ids or []),
        "sql_executed": row.sql_executed,
        "sql_retries": row.sql_retries,
        "guardrail_flags": list(row.guardrail_flags or []),
        "outcome": row.outcome,
        "latency_ms": row.latency_ms,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "prompt_sha256": row.prompt_sha256,
        "prompt_preview": row.prompt_preview,
        "ai_disclosure": bool(row.ai_disclosure),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _apply_filters(
    stmt,
    *,
    username: str | None = None,
    event_type: str | None = None,
    outcome: str | None = None,
    search: str | None = None,
):
    if username and username.strip():
        stmt = stmt.where(func.lower(AuditLog.username) == username.strip().lower())
    if event_type and event_type.strip():
        stmt = stmt.where(AuditLog.event_type == event_type.strip())
    if outcome and outcome.strip():
        stmt = stmt.where(AuditLog.outcome == outcome.strip())
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            or_(
                AuditLog.username.ilike(pattern, escape="\\"),
                AuditLog.event_type.ilike(pattern, escape="\\"),
                AuditLog.request_id.ilike(pattern, escape="\\"),
                AuditLog.thread_id.ilike(pattern, escape="\\"),
                AuditLog.prompt_preview.ilike(pattern, escape="\\"),
                AuditLog.sql_executed.ilike(pattern, escape="\\"),
            )
        )
    return stmt


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return int(ordered[idx])


@router.get("")
async def list_audit_logs(
    username: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated immutable compliance events for C-Level governance."""
    count_stmt = _apply_filters(
        select(func.count()).select_from(AuditLog),
        username=username,
        event_type=event_type,
        outcome=outcome,
        search=search,
    )
    total = int(await db.scalar(count_stmt) or 0)

    rows_stmt = _apply_filters(
        select(AuditLog),
        username=username,
        event_type=event_type,
        outcome=outcome,
        search=search,
    )
    rows_stmt = rows_stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    rows_stmt = rows_stmt.offset(offset).limit(limit)
    rows = list(await db.scalars(rows_stmt))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": [_serialize_audit(r) for r in rows],
    }


@router.get("/summary")
async def audit_logs_summary(
    days: int = Query(default=30, ge=1, le=365),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated AI observability & security KPIs for the requested window."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(
        await db.scalars(select(AuditLog).where(AuditLog.created_at >= since))
    )

    total_events = len(rows)
    chat_turns = 0
    blocked_injections = 0
    pii_redactions = 0
    sql_executions = 0
    sql_retries = 0
    latencies: list[int] = []
    total_input_tokens = 0
    total_output_tokens = 0
    outcomes: dict[str, int] = {}
    event_types: dict[str, int] = {}

    for row in rows:
        ev = row.event_type or "unknown"
        out = row.outcome or "allow"
        flags = list(row.guardrail_flags or [])
        event_types[ev] = event_types.get(ev, 0) + 1
        outcomes[out] = outcomes.get(out, 0) + 1

        if ev == "chat_turn":
            chat_turns += 1
        if out == "block" or any("jailbreak" in f or "injection" in f for f in flags):
            blocked_injections += 1
        if out == "redact" or any(
            f in {"google_api_key", "bearer_sk_key", "github_token", "aws_access_key", "pem_private_key", "jwt_token", "ssn", "payment_card", "external_image_exfil"}
            for f in flags
        ):
            pii_redactions += 1
        if row.sql_executed or (row.mode or "").lower() in {"sql", "hybrid"}:
            sql_executions += 1
            if (row.sql_retries or 0) > 0:
                sql_retries += 1
        if row.latency_ms and row.latency_ms > 0:
            latencies.append(int(row.latency_ms))
        if row.input_tokens:
            total_input_tokens += int(row.input_tokens)
        if row.output_tokens:
            total_output_tokens += int(row.output_tokens)

    avg_latency_ms = int(round(sum(latencies) / len(latencies))) if latencies else 0
    p95_latency_ms = _percentile(latencies, 95.0)
    sql_retry_rate = round(sql_retries / sql_executions, 4) if sql_executions > 0 else 0.0

    return {
        "window_days": days,
        "total_events": total_events,
        "chat_turns": chat_turns,
        "blocked_injections": blocked_injections,
        "pii_redactions": pii_redactions,
        "sql_executions": sql_executions,
        "sql_retries": sql_retries,
        "sql_retry_rate": sql_retry_rate,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "outcomes": outcomes,
        "event_types": event_types,
    }


@router.get("/export")
async def export_audit_logs(
    format: Literal["csv", "ndjson"] = Query(default="csv"),
    username: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=5000),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """Export compliance audit logs cleanly as formula-safe CSV or NDJSON."""
    stmt = _apply_filters(
        select(AuditLog),
        username=username,
        event_type=event_type,
        outcome=outcome,
        search=search,
    )
    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    rows = [_serialize_audit(r) for r in await db.scalars(stmt)]

    if format == "ndjson":
        body = "\n".join(json.dumps(item, ensure_ascii=False) for item in rows)
        if body:
            body += "\n"
        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": 'attachment; filename="finsight-audit-logs.ndjson"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    columns = [
        "event_id",
        "created_at",
        "request_id",
        "thread_id",
        "username",
        "user_role",
        "auth_provider",
        "event_type",
        "mode",
        "model_name",
        "outcome",
        "authorized_doc_count",
        "authorized_dataset_names",
        "cited_doc_ids",
        "cited_chunk_ids",
        "sql_retries",
        "guardrail_flags",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "prompt_sha256",
        "prompt_preview",
        "sql_executed",
        "ai_disclosure",
    ]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for item in rows:
        writer.writerow([sanitize_csv_cell(item.get(col)) for col in columns])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="finsight-audit-logs.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
