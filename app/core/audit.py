"""
app/core/audit.py — Append-only SOC 2 & EU AI Act Art. 50 audit writer and export sanitizer.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AUDIT_STORE_PROMPT_PREVIEW
from app.core.logging_config import get_request_context
from app.db.models import AuditLog
from app.db.session import async_session
from app.rag.guardrails import redact_sensitive_output

logger = logging.getLogger("FinSight.audit")

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_prompt_preview(raw_prompt: str | None) -> tuple[str | None, str | None]:
    """
    Compute deterministic SHA-256 prompt digest and (when enabled) store a
    PII/secret-redacted snippet truncated to 240 characters cleanly.
    """
    if not raw_prompt:
        return (None, None)

    digest = hashlib.sha256(raw_prompt.encode("utf-8", errors="ignore")).hexdigest()
    env_flag = os.getenv("AUDIT_STORE_PROMPT_PREVIEW")
    store_preview = (
        env_flag.strip().lower() == "true"
        if env_flag is not None
        else AUDIT_STORE_PROMPT_PREVIEW
    )
    if not store_preview:
        return (digest, None)

    redacted = redact_sensitive_output(raw_prompt).text
    compact = " ".join(redacted.split())
    preview = compact[:237] + "..." if len(compact) > 240 else compact
    return (digest, preview)


def sanitize_csv_cell(value: Any) -> str:
    """
    Neutralize OWASP CSV/Spreadsheet formula injection prefixes (`=`, `+`, `-`, `@`, tab, CR)
    and normalize line endings cleanly before serializing CSV cells.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        import json

        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)

    normalized = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if normalized.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + normalized
    return normalized


async def record_audit_event(
    *,
    username: str,
    user_role: str,
    event_type: str,
    auth_provider: str = "local",
    request_id: str | None = None,
    thread_id: str | None = None,
    mode: str | None = None,
    model_name: str | None = None,
    authorized_doc_count: int = 0,
    authorized_dataset_names: list[str] | None = None,
    cited_doc_ids: list[int] | None = None,
    cited_chunk_ids: list[str] | None = None,
    sql_executed: str | None = None,
    sql_retries: int = 0,
    guardrail_flags: list[str] | None = None,
    outcome: str = "allow",
    latency_ms: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    raw_prompt: str | None = None,
    ai_disclosure: bool = True,
    db: AsyncSession | None = None,
) -> str | None:
    """
    Persist an immutable append-only compliance audit record cleanly.
    Never raises into interactive request handlers if database is unavailable in unit tests.
    """
    ctx = get_request_context()
    resolved_req_id = request_id or ctx.get("request_id") or str(uuid.uuid4())
    resolved_thread_id = thread_id or ctx.get("thread_id")
    digest, preview = sanitize_prompt_preview(raw_prompt)
    event_id = str(uuid.uuid4())

    row = AuditLog(
        event_id=event_id,
        request_id=resolved_req_id,
        thread_id=resolved_thread_id,
        username=(username or "anonymous").strip(),
        user_role=(user_role or "general").strip(),
        auth_provider=(auth_provider or "local").strip(),
        event_type=event_type.strip(),
        mode=mode,
        model_name=model_name,
        authorized_doc_count=int(authorized_doc_count or 0),
        authorized_dataset_names=list(authorized_dataset_names or []),
        cited_doc_ids=[int(x) for x in (cited_doc_ids or []) if x is not None],
        cited_chunk_ids=[str(x) for x in (cited_chunk_ids or []) if x],
        sql_executed=sql_executed,
        sql_retries=int(sql_retries or 0),
        guardrail_flags=list(dict.fromkeys(str(f) for f in (guardrail_flags or []) if f)),
        outcome=outcome.strip(),
        latency_ms=max(0, int(latency_ms or 0)),
        input_tokens=int(input_tokens) if input_tokens is not None else None,
        output_tokens=int(output_tokens) if output_tokens is not None else None,
        prompt_sha256=digest,
        prompt_preview=preview,
        ai_disclosure=bool(ai_disclosure),
    )

    try:
        if db is not None:
            db.add(row)
            await db.commit()
        else:
            async with async_session() as session:
                session.add(row)
                await session.commit()
        return event_id
    except Exception as exc:
        logger.debug(
            "[Audit] Audit write skipped (%s): %s", type(exc).__name__, exc
        )
        return None
