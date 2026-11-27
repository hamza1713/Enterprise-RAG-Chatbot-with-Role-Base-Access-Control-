"""
tests/test_nextgen_rag.py — Verification of Next-Gen RAG upgrades:
1. PDF table-to-markdown extraction & table-preserving Markdown chunker
2. PostgreSQL pgvector + TSVector hybrid query SQL construction & live role scoping
3. Conversational query contextualization with chat history
4. Atomic Postgres document chunk replacement
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import uuid

from langchain_core.documents import Document
import pytest
from sqlalchemy import delete

from app.api.chat import ChatMessage, contextualize_query_llm
from app.core.config import EMBEDDING_DIMENSIONS
from app.db.models import DocumentRecord
from app.db.session import sync_session
from app.rag.pgvector_store import (
    PgVectorHybridStore,
    build_hybrid_rrf_sql,
    has_meaningful_lexical_terms,
    role_predicate_clause,
)
from app.rag.processors import MarkdownSemanticChunker, _format_table_as_markdown


def test_format_table_as_markdown():
    """Verify 2D table arrays are formatted as valid GitHub Flavored Markdown."""
    table = [
        ["Department", "Headcount", "Budget"],
        ["Finance", "12", "$2.5M"],
        ["Engineering", "45", "$8.1M"],
    ]
    md = _format_table_as_markdown(table)
    assert "| Department | Headcount | Budget |" in md
    assert "| --- | --- | --- |" in md
    assert "| Finance | 12 | $2.5M |" in md
    assert "| Engineering | 45 | $8.1M |" in md


def test_format_table_handles_empty_or_ragged_rows():
    """Verify table formatter handles ragged rows and None cells safely."""
    table = [
        ["Metric", "2023", "2024"],
        ["Revenue", "$100M"],
        [None, None, None],
    ]
    md = _format_table_as_markdown(table)
    assert "| Metric | 2023 | 2024 |" in md
    assert "| Revenue | $100M |  |" in md


def test_markdown_chunker_keeps_tables_intact():
    """MarkdownSemanticChunker keeps medium tables intact instead of splitting mid-row."""
    table_rows = "\n".join(f"| Row {i} | ${i * 100} |" for i in range(1, 15))
    md_doc = Document(
        page_content=f"# Financials\n\nSummary text.\n\n| Item | Amount |\n| --- | --- |\n{table_rows}\n",
        metadata={"role": "finance", "source": "fin.md"},
    )
    chunks = MarkdownSemanticChunker(chunk_size=200, chunk_overlap=30).chunk(md_doc)
    table_chunks = [c for c in chunks if "| Item | Amount |" in c.page_content]
    assert len(table_chunks) == 1
    assert "| Row 14 | $1400 |" in table_chunks[0].page_content


def test_pgvector_role_predicate_and_rrf_sql():
    """Both dense and sparse CTEs embed strict role predicates."""
    clause_cl, params_cl = role_predicate_clause("c-level")
    assert clause_cl == "TRUE" and params_cl == {}

    clause_gen, _ = role_predicate_clause("general")
    assert clause_gen == "LOWER(role) = 'general'"

    clause_hr, params_hr = role_predicate_clause("HR")
    assert "LOWER(role) = :role_lower" in clause_hr
    assert "LOWER(role) = 'general'" in clause_hr
    assert params_hr == {"role_lower": "hr"}

    sql, sql_params = build_hybrid_rrf_sql("hr", include_sparse=True)
    assert sql.count("LOWER(role) = :role_lower") == 2
    assert "websearch_to_tsquery('english', :query_text)" in sql
    assert sql_params == {"role_lower": "hr"}
    assert has_meaningful_lexical_terms("what is this") is False
    assert has_meaningful_lexical_terms("SOC2-CC6.1") is True


@pytest.mark.postgres
def test_pgvector_hybrid_and_tsvector_search_and_cleanup(postgres_ready):
    """Verify Postgres TSVector + pgvector stores chunks atomically and scopes roles."""
    store = PgVectorHybridStore()
    vec = [0.01] * EMBEDDING_DIMENSIONS
    vec[0] = 1.0

    with sync_session() as db:
        d_eng = DocumentRecord(
            filename=f"sec_{uuid.uuid4().hex[:6]}.pdf",
            role="Engineering",
            object_key=f"documents/Engineering/{uuid.uuid4().hex}_sec.pdf",
        )
        d_mkt = DocumentRecord(
            filename=f"mkt_{uuid.uuid4().hex[:6]}.pdf",
            role="Marketing",
            object_key=f"documents/Marketing/{uuid.uuid4().hex}_mkt.pdf",
        )
        db.add_all([d_eng, d_mkt])
        db.commit()
        eng_id, mkt_id = d_eng.id, d_mkt.id

    try:
        store.replace_document_chunks_sync(
            doc_id=eng_id,
            role="engineering",
            source="security_audit.pdf",
            chunks=[
                Document(
                    page_content="Policy SOC2-CC6.1 requires quarterly access control audits.",
                    metadata={"source": "security_audit.pdf", "role": "engineering"},
                )
            ],
            vectors=[vec],
        )
        store.replace_document_chunks_sync(
            doc_id=mkt_id,
            role="marketing",
            source="marketing_plan.pdf",
            chunks=[
                Document(
                    page_content="SOC2-CC6.1 marketing campaign launch budget Q4.",
                    metadata={"source": "marketing_plan.pdf", "role": "marketing"},
                )
            ],
            vectors=[vec],
        )

        lex_results = store.lexical_search("SOC2-CC6.1", user_role="engineering", limit=10)
        assert len(lex_results) >= 1
        assert any("SOC2-CC6.1" in d.page_content for d in lex_results)
        assert all(d.metadata["role"] in ("engineering", "general") for d in lex_results)

        hyb_results = store.search(
            "SOC2-CC6.1",
            user_role="engineering",
            limit=10,
            rerank=False,
            query_vector=vec,
        )
        assert all(d.metadata["role"] in ("engineering", "general") for d in hyb_results)
        assert any(d.metadata["doc_id"] == eng_id for d in hyb_results)
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id.in_([eng_id, mkt_id])))
            db.commit()


def test_contextualize_query_llm_without_history():
    """When history is empty, question must be returned unchanged without LLM call."""
    q = "What is the marketing budget?"
    assert contextualize_query_llm(q, []) == q


def test_contextualize_query_llm_with_history():
    """When history is present, query contextualizer reformulates ambiguous pronouns."""
    history = [
        ChatMessage(role="user", content="What was the headcount in Engineering for 2024?"),
        ChatMessage(role="assistant", content="Engineering had 45 employees in 2024."),
    ]
    follow_up = "What was their total budget?"

    mock_llm_resp = MagicMock()
    mock_llm_resp.content = "What was the total budget for Engineering in 2024?"

    with patch("app.rag.module.model") as mock_model:
        mock_model.invoke.return_value = mock_llm_resp
        standalone = contextualize_query_llm(follow_up, history)
        assert "Engineering in 2024" in standalone
