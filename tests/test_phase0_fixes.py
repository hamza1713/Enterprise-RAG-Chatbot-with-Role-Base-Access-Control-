"""
tests/test_phase0_fixes.py — Regression suite preserving all Phase 0 security & stability invariants.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import math
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
import pytest
from sqlalchemy import delete, select
from starlette.requests import Request

from app.core.cache import CacheManager, InMemoryTTLCache, cache_manager
from app.core.config import EMBEDDING_DIMENSIONS
from app.core.limiter import get_client_ip
from app.core.users import _DEFAULT_USERS
from app.db.models import DocumentChunk, DocumentRecord, EvaluationRun
from app.db.session import sync_session
from app.main import app
from app.storage import get_storage_backend

client = TestClient(app)


def _get_token(username: str, password: str) -> str:
    res = client.get("/login", auth=(username, password))
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ── 1. Users / Auth Hygiene ───────────────────────────────────────────────────


def test_default_users_do_not_include_hamza():
    usernames = {u[0].lower() for u in _DEFAULT_USERS}
    assert "hamza" not in usernames


@pytest.mark.postgres
def test_hamza_login_rejected(postgres_ready):
    for pwd in ("admin123", "", "hamza"):
        res = client.get("/login", auth=("Hamza", pwd))
        assert res.status_code == 401


# ── 2. Conversational Classifier ──────────────────────────────────────────────


def test_classifier_handles_greetings_vs_domain_queries():
    from app.rag.classifier import is_conversational_query

    assert is_conversational_query("hi") is True
    assert is_conversational_query("Hello team!") is True
    assert is_conversational_query("thanks!") is True

    assert is_conversational_query("history of 2024") is False
    assert is_conversational_query("types of expenses") is False
    assert is_conversational_query("okr summary") is False
    assert is_conversational_query("help me list payroll") is False
    assert is_conversational_query("hi, what was Q3 revenue?") is False


# ── 3. sqlglot AST SQL Safety Guard & Table Extraction ────────────────────────


def test_csv_query_sqlglot_allows_safe_queries_and_ctes():
    from app.rag.csv_query import extract_tables_from_sql, is_safe_query

    assert is_safe_query("SELECT created_at, updated_at, delete_flag FROM hr_data") is True
    cte_sql = (
        "WITH cte AS (SELECT * FROM hr_data) "
        "SELECT cte.id, f.amount FROM cte JOIN finance_data f ON cte.id = f.id"
    )
    assert is_safe_query(cte_sql) is True
    tables = extract_tables_from_sql(cte_sql)
    assert "hr_data" in tables
    assert "finance_data" in tables
    assert "cte" not in tables


def test_csv_query_sqlglot_rejects_unsafe_or_multi_statement_sql():
    from app.rag.csv_query import is_safe_query

    for bad_sql in [
        "DROP TABLE hr_data",
        "DELETE FROM hr_data WHERE id = 1",
        "SELECT * FROM hr_data; DROP TABLE hr_data",
        "PRAGMA table_info('hr_data')",
        "COPY hr_data TO '/tmp/dump.csv'",
        "SELECT * FROM read_csv_auto('secret.csv')",
    ]:
        assert is_safe_query(bad_sql) is False, f"Expected unsafe SQL rejected: {bad_sql}"


# ── 4. RAG Chunk Atomicity, Reindex, TSVector Stopwords & LCEL Streaming ─────


@pytest.mark.postgres
def test_replace_chunks_is_atomic_and_preserves_old_chunks_on_embed_failure(postgres_ready):
    from app.rag import module as rag_module

    storage = get_storage_backend()
    obj_key = storage.put_bytes(
        f"documents/HR/{uuid.uuid4().hex}_atomic.md",
        b"# Atomic Policy\nKeep existing chunks until new embeddings finish cleanly.",
        content_type="text/markdown",
    )
    with sync_session() as db:
        doc = DocumentRecord(
            filename=f"atomic_{uuid.uuid4().hex[:6]}.md",
            role="HR",
            object_key=obj_key,
            embedded=1,
            total_chunks=1,
            embedded_chunks=1,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    vec = [0.0] * EMBEDDING_DIMENSIONS
    vec[0] = 1.0

    try:
        store = rag_module.get_hybrid_store()
        store.replace_document_chunks_sync(
            doc_id=doc_id,
            role="hr",
            source="atomic.md",
            chunks=[Document(page_content="preserved old text", metadata={"role": "hr"})],
            vectors=[vec],
        )

        failing_embed = MagicMock()
        failing_embed.aembed_documents = AsyncMock(side_effect=RuntimeError("embedding batch failed"))

        with patch.object(rag_module, "embeddings_service", failing_embed), patch.dict(
            "os.environ", {"CONTEXTUAL_RETRIEVAL_ENABLED": "false"}
        ):
            with pytest.raises(RuntimeError, match="embedding batch failed"):
                asyncio.run(rag_module.ingest_single_document(doc_id))

        with sync_session() as db:
            chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)))
            assert len(chunks) == 1
            assert chunks[0].raw_content == "preserved old text"
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.commit()
        storage.delete(obj_key)


def test_rag_chain_supports_lcel_astream_and_mock_invoke():
    from app.rag import module as rag_module

    fake_store = MagicMock()
    doc = Document(
        page_content="Q3 revenue increased by 15%.",
        metadata={"source": "q3.md", "role": "finance", "chunk_id": "1_0", "rrf_score": 0.92},
    )
    fake_store.search.return_value = [doc]
    fake_store.asearch = AsyncMock(return_value=[doc])
    fake_store._rerank_if_configured.side_effect = lambda query, candidates, top_n, cohere_key=None: candidates[:top_n]

    async def _collect_stream():
        fake_llm = FakeListChatModel(responses=["Revenue grew 15% year over year."])
        with patch.object(rag_module, "hybrid_store", fake_store), patch.object(
            rag_module, "expand_query", return_value=["Q3 revenue"]
        ), patch.object(rag_module, "model", fake_llm):
            chain = rag_module.get_rag_chain("finance")
            answer_chunks: list[str] = []
            seen_context = []
            async for chunk in chain.astream({"input": "What was Q3 revenue?"}):
                if "context" in chunk:
                    seen_context.extend(chunk["context"])
                if "answer" in chunk and chunk["answer"]:
                    answer_chunks.append(chunk["answer"])
            return answer_chunks, seen_context

    chunks, ctx = asyncio.run(_collect_stream())
    assert len(chunks) > 1
    assert "".join(chunks) == "Revenue grew 15% year over year."
    assert len(ctx) >= 1

    mock_model = MagicMock()
    mock_model.invoke.return_value = MagicMock(content="Mocked revenue answer.")
    with patch.object(rag_module, "hybrid_store", fake_store), patch.object(
        rag_module, "expand_query", return_value=["Q3 revenue"]
    ), patch.object(rag_module, "model", mock_model):
        chain = rag_module.get_rag_chain("finance")
        out = chain.invoke({"input": "What was Q3 revenue?"})
    assert out["answer"] == "Mocked revenue answer."
    assert len(out["context"]) >= 1


# ── 5. Admin Reindex Endpoint ─────────────────────────────────────────────────


@pytest.mark.postgres
def test_admin_reindex_uses_non_destructive_trigger_and_clears_cache(postgres_ready):
    token = _get_token("admin", "admin123")
    cache_manager.clear()
    cache_manager.set("finsight:cache:hr:sample", {"answer": "stale"})
    assert cache_manager.get("finsight:cache:hr:sample") is not None

    fake_job_id = str(uuid.uuid4())
    with patch(
        "app.api.admin.enqueue_full_reindex_job",
        new=AsyncMock(return_value=(fake_job_id, 4)),
    ) as mock_enqueue:
        res = client.post("/reindex", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["queued_docs"] == 4
    assert body["job_id"] == fake_job_id
    mock_enqueue.assert_called_once()
    assert cache_manager.get("finsight:cache:hr:sample") is None


# ── 6. Chat Stream Cache Ordering & History-Aware Key ─────────────────────────


@pytest.mark.postgres
def test_chat_stream_checks_cache_before_classifier_and_tracks_history(postgres_ready):
    token = _get_token("hr", "hr123")
    cache_manager.clear()

    class _FakeStreamChain:
        async def astream(self, payload):
            yield {"context": [Document(page_content="Leave policy", metadata={"source": "leave.md"})]}
            for tok in ("Employees get ", "20 paid leave days."):
                yield {"answer": tok}

    with patch("app.api.chat.detect_query_type_llm", return_value="RAG") as mock_clf, patch(
        "app.api.chat.get_rag_chain", return_value=_FakeStreamChain()
    ):
        r1 = client.post(
            "/chat-stream",
            json={"question": "How many leave days do employees get?", "history": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200
        events1 = [json.loads(line) for line in r1.text.strip().splitlines()]
        meta1 = [e for e in events1 if e["type"] == "metadata"][-1]
        tokens1 = "".join(e["content"] for e in events1 if e["type"] == "token")
        assert meta1["cached"] is False
        assert tokens1 == "Employees get 20 paid leave days."

        r2 = client.post(
            "/chat-stream",
            json={"question": "How many leave days do employees get?", "history": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        events2 = [json.loads(line) for line in r2.text.strip().splitlines()]
        meta2 = [e for e in events2 if e["type"] == "metadata"][-1]
        tokens2 = "".join(e["content"] for e in events2 if e["type"] == "token")
        assert meta2["cached"] is True
        assert tokens2 == tokens1
        assert mock_clf.call_count == 1

    k_a = cache_manager.build_cache_key(
        "hr", "What is their budget?", history=[{"role": "user", "content": "Tell me about Team A"}]
    )
    k_b = cache_manager.build_cache_key(
        "hr", "What is their budget?", history=[{"role": "user", "content": "Tell me about Team B"}]
    )
    assert k_a != k_b
    cache_manager.clear()


# ── 7. Thread-Safe InMemoryTTLCache & Redis SCAN Deletion ─────────────────────


def test_in_memory_cache_thread_safety():
    cache = InMemoryTTLCache(max_size=50)
    errors: list[Exception] = []

    def _worker(tid: int):
        try:
            for i in range(40):
                key = f"finsight:cache:role{tid % 3}:{i}"
                cache.set(key, {"v": i}, ttl=60)
                cache.get(key)
                if i % 10 == 0:
                    cache.delete_prefix(f"finsight:cache:role{tid % 3}:")
        except Exception as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_worker, range(8)))

    assert errors == []


def test_cache_manager_uses_scan_iter_never_keys():
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    fake_redis.scan_iter.return_value = iter(["finsight:cache:hr:k1", "finsight:cache:hr:k2"])
    fake_redis.delete.return_value = 2

    with patch("redis.from_url", return_value=fake_redis):
        mgr = CacheManager(redis_url="redis://localhost:6379/0")

    deleted = mgr.delete_prefix("finsight:cache:hr:")
    assert deleted == 2
    fake_redis.scan_iter.assert_called_with(match="finsight:cache:hr:*", count=500)
    fake_redis.keys.assert_not_called()

    fake_redis.scan_iter.return_value = iter(["finsight:cache:hr:k3"])
    fake_redis.delete.return_value = 1
    mgr.clear()
    fake_redis.scan_iter.assert_called_with(match="finsight:cache:*", count=500)
    fake_redis.keys.assert_not_called()


# ── 8. Trusted Proxy Client IP Extraction ─────────────────────────────────────


def _make_request(remote_ip: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/chat",
            "headers": raw_headers,
            "client": (remote_ip, 54321),
        }
    )


def test_limiter_ignores_xff_from_untrusted_peer_and_trusts_proxy_hop():
    untrusted_req = _make_request(
        "203.0.113.5", headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert get_client_ip(untrusted_req) == "203.0.113.5"

    proxied_req = _make_request(
        "127.0.0.1", headers={"X-Forwarded-For": "198.51.100.7, 127.0.0.1"}
    )
    assert get_client_ip(proxied_req) == "198.51.100.7"


# ── 9. Documents Listing Fields & CSV Server-Side Pagination ──────────────────


@pytest.mark.postgres
def test_documents_list_fields_and_csv_pagination(postgres_ready):
    storage = get_storage_backend()
    lines = ["id,val"] + [f"{i},{i * 10}" for i in range(12)]
    csv_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    obj_key = storage.put_bytes(
        f"documents/HR/{uuid.uuid4().hex}_phase0_paginated.csv",
        csv_bytes,
        content_type="text/csv",
    )

    with sync_session() as db:
        doc = DocumentRecord(
            filename=f"phase0_paginated_{uuid.uuid4().hex[:6]}.csv",
            role="hr",
            object_key=obj_key,
            headers_str="id,val",
            size_bytes=len(csv_bytes),
            embedded=1,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    token = _get_token("hr", "hr123")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        list_res = client.get("/documents", headers=headers)
        assert list_res.status_code == 200
        matches = [d for d in list_res.json() if d["id"] == doc_id]
        assert len(matches) == 1
        assert matches[0]["role"] == "hr"
        assert matches[0]["headers_str"] == "id,val"

        p1 = client.get(
            "/documents/content",
            params={"doc_id": doc_id, "limit": 5, "offset": 0},
            headers=headers,
        )
        assert p1.status_code == 200
        b1 = p1.json()
        assert b1["total_rows"] == 12
        assert b1["offset"] == 0
        assert b1["limit"] == 5
        assert b1["truncated"] is True
        assert len(b1["data"]) == 5

        p3 = client.get(
            "/documents/content",
            params={"filepath": obj_key, "limit": 5, "offset": 10},
            headers=headers,
        )
        assert p3.status_code == 200
        b3 = p3.json()
        assert b3["total_rows"] == 12
        assert b3["offset"] == 10
        assert len(b3["data"]) == 2
        assert b3["truncated"] is False
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.commit()
        storage.delete(obj_key)


# ── 10. Health & Readiness Endpoints ──────────────────────────────────────────


@pytest.mark.postgres
def test_health_and_readiness_endpoints(postgres_ready):
    r_root = client.get("/")
    r_health = client.get("/health")
    assert r_root.status_code == 200
    assert r_health.status_code == 200
    assert r_root.json() == r_health.json() == {"status": "ok", "service": "FinSight API"}

    with patch("app.api.health.REDIS_URL", ""):
        r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ready"
    assert r_ready.json()["checks"]["postgres"] == "ok"
    assert r_ready.json()["checks"]["storage"] == "ok"

    fake_redis_client = MagicMock()
    fake_redis_client.ping.side_effect = RuntimeError("redis down")
    with patch("app.api.health.REDIS_URL", "redis://localhost:6379/0"), patch.object(
        cache_manager, "using_redis", False
    ), patch("redis.from_url", return_value=fake_redis_client):
        r_fail_redis = client.get("/ready")
    assert r_fail_redis.status_code == 503
    assert r_fail_redis.json()["checks"]["redis"] == "error"


# ── 11. Evaluation NaN Sanitization & Ground Truth Preservation ───────────────


def test_evaluate_status_sanitizes_nan_and_inf():
    from app.workers.tasks import _sanitize_json_numbers

    sanitized = _sanitize_json_numbers(
        {"overall": {"faithfulness": float("nan"), "relevancy": math.inf, "ok": 0.91}}
    )
    dumped = json.dumps(sanitized, allow_nan=False)
    assert "NaN" not in dumped and "Infinity" not in dumped
    assert sanitized["overall"]["faithfulness"] is None
    assert sanitized["overall"]["relevancy"] is None
    assert sanitized["overall"]["ok"] == 0.91


@pytest.mark.postgres
def test_evaluate_status_endpoint_persists_postgres_sanitized_scores(postgres_ready):
    token = _get_token("admin", "admin123")
    run_id = str(uuid.uuid4())
    with sync_session() as db:
        run = EvaluationRun(
            id=run_id,
            mode="full",
            status="completed",
            overall_scores={"faithfulness": None, "relevancy": 0.85},
            rbac_overall="PASS",
        )
        db.add(run)
        db.commit()
    try:
        res = client.get("/evaluate/status", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "completed"
        assert body["overall"]["relevancy"] == 0.85
    finally:
        with sync_session() as db:
            db.execute(delete(EvaluationRun).where(EvaluationRun.id == run_id))
            db.commit()


def test_eval_dataset_does_not_mask_empty_answer_or_contexts(tmp_path):
    from app.rag_evaluator.eval_dataset import (
        load_builtin_dataset_with_rag,
        load_ragas_dataset_from_csv,
    )

    qa_csv = tmp_path / "qa.csv"
    qa_csv.write_text(
        "question,answer,role,source\n"
        '"What was 2024 revenue?","Ground truth 42M.",finance,report.md\n',
        encoding="utf-8",
    )

    with patch("app.rag_evaluator.eval_dataset._run_rag_for_role", return_value=("", [])):
        ds_csv = load_ragas_dataset_from_csv(
            csv_path=str(qa_csv),
            roles_filter=["finance"],
            max_per_role=5,
            sleep_between_calls=0,
        )
        assert ds_csv[0]["response"] == ""
        assert ds_csv[0]["retrieved_contexts"] == [""]
        assert ds_csv[0]["reference"] == "Ground truth 42M."

        ds_builtin = load_builtin_dataset_with_rag(
            roles=["hr"],
            sleep_between_calls=0,
        )
        assert len(ds_builtin) >= 1
        for row in ds_builtin:
            assert row["response"] == ""
            assert row["retrieved_contexts"] == [""]
            assert row["reference"] != ""
