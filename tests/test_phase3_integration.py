"""
tests/test_phase3_integration.py — Live PostgreSQL 17 tests for Phase 3 audit immutability & APIs.
Executed cleanly in CI where PostgreSQL 17 + Alembic migrations are active.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
import pytest


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_audit_logs_append_only_trigger_and_summary(monkeypatch):
    from app.core.audit import record_audit_event
    from app.db.session import async_session

    monkeypatch.setenv("AUDIT_STORE_PROMPT_PREVIEW", "true")

    event_id = await record_audit_event(
        username="finance_user",
        user_role="Finance",
        auth_provider="local",
        event_type="chat_turn",
        mode="RAG",
        model_name="gemini-3.8-flash",
        authorized_doc_count=2,
        authorized_dataset_names=["finance_data"],
        cited_doc_ids=[1],
        cited_chunk_ids=["chunk_1"],
        guardrail_flags=["ssn"],
        outcome="redact",
        latency_ms=250,
        input_tokens=100,
        output_tokens=40,
        raw_prompt="What was EBITDA? SSN 123-45-6789",
    )
    assert event_id is not None

    async with async_session() as db:
        row = (
            await db.execute(
                text(
                    "SELECT prompt_preview, outcome, authorized_doc_count "
                    "FROM audit_logs WHERE event_id = :eid"
                ),
                {"eid": event_id},
            )
        ).one()
        assert "[REDACTED-SSN]" in (row[0] or "")
        assert row[1] == "redact"
        assert row[2] == 2

        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(
                text("UPDATE audit_logs SET outcome = 'allow' WHERE event_id = :eid"),
                {"eid": event_id},
            )
            await db.commit()
        await db.rollback()

        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(
                text("DELETE FROM audit_logs WHERE event_id = :eid"),
                {"eid": event_id},
            )
            await db.commit()
        await db.rollback()
