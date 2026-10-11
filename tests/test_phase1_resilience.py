"""
tests/test_phase1_resilience.py — Verification suite for Phase 1: Rate Limiting & Multi-Tier Caching.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.limiter import limiter
from app.core.cache import cache_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure a clean cache for each test."""
    cache_manager.clear()
    yield
    cache_manager.clear()


@pytest.fixture
def admin_headers():
    res = client.get("/login", auth=("admin", "admin123"))
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hr_headers():
    res = client.get("/login", auth=("hr", "hr123"))
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def marketing_headers():
    res = client.get("/login", auth=("marketing", "marketing123"))
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── 1. Rate Limiting Tests ───────────────────────────────────────────────────

def test_login_rate_limiting():
    """Verify that /login triggers HTTP 429 after 5 requests within a minute."""
    limiter.enabled = True
    try:
        # 5 requests should pass (or some already consumed, so loop up to 6)
        responses = []
        for _ in range(6):
            res = client.get("/login", auth=("admin", "admin123"))
            responses.append(res.status_code)

        # The 6th request MUST be 429 Too Many Requests
        assert 429 in responses, f"Expected 429 in responses, got: {responses}"
        last_429 = client.get("/login", auth=("admin", "admin123"))
        assert last_429.status_code == 429
        assert "Rate limit exceeded" in last_429.json().get("detail", "")
    finally:
        limiter.enabled = False


# ── 2. Cache Hit & Speed Tests ───────────────────────────────────────────────

@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "Employees receive 20 PTO days.", "sources": ["handbook.pdf"]})
def test_chat_cache_hit(mock_rag, mock_detect, admin_headers):
    """Verify that identical questions return cached responses on subsequent calls."""
    question = "What is the employee PTO policy?"

    # 1st call: Cache miss
    res1 = client.post("/chat", headers=admin_headers, json={"question": question})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["cached"] is False
    assert data1["answer"] == "Employees receive 20 PTO days."
    assert mock_rag.call_count == 1

    # 2nd call: Cache hit (mock_rag should NOT be called again!)
    res2 = client.post("/chat", headers=admin_headers, json={"question": question})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["cached"] is True
    assert data2["answer"] == "Employees receive 20 PTO days."
    assert mock_rag.call_count == 1  # Still 1, meaning LLM was bypassed!


# ── 3. Role-Scoped Cache Isolation (Security Guardrail) ──────────────────────

@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag")
def test_role_scoped_cache_isolation(mock_rag, mock_detect, hr_headers, marketing_headers):
    """Verify that cached answers for role HR are NEVER returned to Marketing."""
    mock_rag.return_value = {"answer": "HR-specific leave breakdown.", "sources": ["hr_leave.pdf"]}
    question = "How do leave policies work?"

    # HR queries: Cache miss for HR
    res_hr = client.post("/chat", headers=hr_headers, json={"question": question})
    assert res_hr.status_code == 200
    assert res_hr.json()["cached"] is False
    assert res_hr.json()["answer"] == "HR-specific leave breakdown."

    # Marketing queries the EXACT SAME question:
    mock_rag.return_value = {"answer": "Marketing general policies.", "sources": ["marketing_guide.pdf"]}
    res_mkt = client.post("/chat", headers=marketing_headers, json={"question": question})
    assert res_mkt.status_code == 200
    # Must NOT hit HR's cache!
    assert res_mkt.json()["cached"] is False
    assert res_mkt.json()["answer"] == "Marketing general policies."


# ── 4. Cache Invalidation on Upload ──────────────────────────────────────────

def test_cache_invalidation_on_upload():
    """Verify that uploading or calling invalidation clears role cache keys."""
    key_hr = cache_manager.build_cache_key("HR", "What are leave rules?")
    cache_manager.set(key_hr, {"answer": "Old HR rules", "sources": []})

    key_mkt = cache_manager.build_cache_key("Marketing", "What are brand rules?")
    cache_manager.set(key_mkt, {"answer": "Brand logo guide", "sources": []})

    assert cache_manager.get(key_hr) is not None
    assert cache_manager.get(key_mkt) is not None

    # Invalidate HR prefix (simulating upload for HR role)
    cache_manager.delete_prefix("finsight:cache:hr:")

    # HR cache is cleared, but Marketing cache is intact
    assert cache_manager.get(key_hr) is None
    assert cache_manager.get(key_mkt) is not None


# ── 5. Streaming Cache Replay ────────────────────────────────────────────────

@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "| ID | Name |\n|---|---|\n| 1 | Alice |", "sql": "SELECT 1"})
def test_chat_stream_cache_replay(mock_csv, mock_detect, admin_headers):
    """Verify that /chat-stream properly caches and replays cached tokens."""
    question = "Show alice record"

    # 1st call: Stream and cache
    res1 = client.post("/chat-stream", headers=admin_headers, json={"question": question})
    assert res1.status_code == 200
    lines1 = [json.loads(line) for line in res1.text.strip().split("\n") if line]
    meta1 = [l for l in lines1 if l.get("type") == "metadata"][0]
    assert meta1.get("cached") is False

    # 2nd call: Replay from cache
    res2 = client.post("/chat-stream", headers=admin_headers, json={"question": question})
    assert res2.status_code == 200
    lines2 = [json.loads(line) for line in res2.text.strip().split("\n") if line]
    meta2 = [l for l in lines2 if l.get("type") == "metadata"][0]
    assert meta2.get("cached") is True

    # Tokens should match
    tokens1 = "".join([l.get("content", "") for l in lines1 if l.get("type") == "token"])
    tokens2 = "".join([l.get("content", "") for l in lines2 if l.get("type") == "token"])
    assert tokens1 == tokens2
