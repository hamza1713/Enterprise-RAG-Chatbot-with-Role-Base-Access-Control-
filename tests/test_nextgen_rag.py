"""
tests/test_nextgen_rag.py — Verification of Next-Gen RAG upgrades:
1. PDF table-to-markdown extraction
2. SQLite FTS5 BM25 hybrid search
3. Conversational query contextualization with chat history
4. Idempotent document chunking and cleanup
"""

import re
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document

from app.rag.processors import _format_table_as_markdown, PDFDocumentLoader
from app.api.chat import ChatMessage, contextualize_query_llm
from app.core.database import get_db_conn
from app.rag.module import HybridMultiQueryRetriever, _embed_chunks_to_vectorstore


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
        ["Revenue", "$100M"],  # ragged row
        [None, None, None],     # empty row
    ]
    md = _format_table_as_markdown(table)
    assert "| Metric | 2023 | 2024 |" in md
    assert "| Revenue | $100M |  |" in md


def test_sqlite_fts5_bm25_search_and_cleanup():
    """Verify SQLite FTS5 indexes chunks and retrieves exact codes with role scoping."""
    conn = get_db_conn()
    doc_id = 9999
    conn.execute("DELETE FROM document_chunks_fts WHERE doc_id = ?", (str(doc_id),))
    conn.commit()

    # Insert test chunks
    chunks = [
        Document(
            page_content="Policy SOC2-CC6.1 requires quarterly access control audits.",
            metadata={"source": "security_audit.pdf", "role": "engineering"}
        ),
        Document(
            page_content="Marketing budget allocation for campaign Q4.",
            metadata={"source": "marketing_plan.pdf", "role": "marketing"}
        )
    ]

    # Test idempotent chunk storage
    with patch("app.rag.module.vectorstore") as mock_vs:
        _embed_chunks_to_vectorstore(chunks, doc_id=doc_id)

    retriever = HybridMultiQueryRetriever(user_role="engineering")
    results = retriever._search_fts5("SOC2-CC6.1", limit=5)

    assert len(results) >= 1
    assert any("SOC2-CC6.1" in doc.page_content for doc in results)
    assert all(doc.metadata["role"] in ("engineering", "general") for doc in results)

    # Clean up test rows
    conn.execute("DELETE FROM document_chunks_fts WHERE doc_id = ?", (str(doc_id),))
    conn.commit()
    conn.close()


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
