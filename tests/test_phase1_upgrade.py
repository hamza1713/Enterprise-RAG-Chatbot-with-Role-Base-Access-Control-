"""
tests/test_phase1_upgrade.py — Comprehensive Phase 1 verification suite covering:
  - Stateless ObjectStorageBackend (LocalObjectStorage + S3ObjectStorage mocked)
  - Parquet + ephemeral :memory: DuckDB sandbox isolation
  - DoclingServePDFParser HTTP conversion + pdfplumber fallback
  - Contextual Retrieval enrichment + offline fallback
  - GeminiEmbedding2Service 1536-dim asymmetric prefixes & error handling
  - Lazy model/store initialization (zero DUMMY_KEY import side effects)
  - Postgres CRUD APIs, immediate token_version JWT revocation, & Taskiq durable jobs
"""

from __future__ import annotations

import asyncio
from io import BytesIO
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from botocore.exceptions import ClientError
import duckdb
from fastapi.testclient import TestClient
import httpx
from langchain_core.documents import Document
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import delete, select

from app.core.sql_sandbox import query_authorized_parquet_tables
from app.db.models import DatasetTable, DocumentChunk, DocumentRecord, EvaluationRun, JobRecord, Role, User
from app.db.session import sync_session
from app.main import app
from app.rag import module as rag_module
from app.rag.contextualizer import contextualize_chunks
from app.rag.embeddings import (
    GeminiEmbedding2Service,
    format_document_for_embedding,
    format_query_for_embedding,
)
from app.rag.processors import DoclingServePDFParser
from app.storage import LocalObjectStorage, S3ObjectStorage, get_storage_backend

client = TestClient(app)


def _login(username: str, password: str) -> dict[str, str]:
    res = client.get("/login", auth=(username, password))
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION A — Offline Component & Architecture Unit Tests
# ══════════════════════════════════════════════════════════════════════════════


def test_import_rag_module_has_zero_dummy_key_clients():
    # Import in a fresh interpreter: earlier tests in this process legitimately build the
    # lazy singletons, so checking them here would test call order, not import-time behaviour.
    import subprocess
    import sys

    probe = (
        "import app.rag.module as m; "
        "print(m.model is None, m.hybrid_store is None, m.embeddings_service is None)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "True True True"


def test_local_object_storage_crud_and_traversal_guards(tmp_path):
    store = LocalObjectStorage(root_dir=tmp_path)
    store.ensure_bucket()

    key = store.put_bytes("documents/HR/report.md", b"# Leave Policy\n20 days PTO.", content_type="text/markdown")
    assert key == "documents/HR/report.md"
    assert store.exists(key) is True
    assert store.get_bytes(key) == b"# Leave Policy\n20 days PTO."

    with store.open_local_temp(key) as tmp_path_obj:
        assert tmp_path_obj.exists()
        assert tmp_path_obj.read_bytes() == b"# Leave Policy\n20 days PTO."
        leaked_path = tmp_path_obj
    assert not leaked_path.exists()

    store.delete(key)
    assert store.exists(key) is False
    with pytest.raises(FileNotFoundError):
        store.get_bytes(key)

    for bad_key in ("../secret.txt", "documents/../../escape", "C:evil.txt", "a\x00b"):
        with pytest.raises(ValueError):
            store.put_bytes(bad_key, b"x")


def test_s3_object_storage_operations_with_mock_boto():
    fake_boto = MagicMock()
    not_found_err = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
    fake_boto.head_bucket.side_effect = not_found_err
    fake_boto.get_object.return_value = {"Body": BytesIO(b"hello-s3")}

    with patch("boto3.client", return_value=fake_boto):
        s3 = S3ObjectStorage(
            bucket="finsight-test",
            endpoint_url="http://minio:9000",
            access_key="k",
            secret_key="s",
        )
        s3.ensure_bucket()
        fake_boto.create_bucket.assert_called_once_with(Bucket="finsight-test")

        stored = s3.put_bytes("/documents/Finance/q4.pdf", b"%PDF-1.4", content_type="application/pdf")
        assert stored == "documents/Finance/q4.pdf"
        fake_boto.put_object.assert_called_once()
        assert s3.get_bytes(stored) == b"hello-s3"

        no_key_err = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        fake_boto.get_object.side_effect = no_key_err
        with pytest.raises(FileNotFoundError):
            s3.get_bytes("documents/Finance/missing.pdf")


def test_parquet_duckdb_sandbox_executes_authorized_and_blocks_escape(tmp_path):
    store = LocalObjectStorage(root_dir=tmp_path)
    df_allowed = pd.DataFrame({"dept": ["HR", "HR"], "headcount": [12, 18]})
    df_secret = pd.DataFrame({"secret_bonus": [999999]})

    def _to_parquet(df: pd.DataFrame) -> bytes:
        buf = BytesIO()
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), buf, compression="snappy")
        return buf.getvalue()

    hr_key = store.put_bytes("datasets/HR/1/hr_staff.parquet", _to_parquet(df_allowed))
    fin_key = store.put_bytes("datasets/Finance/2/fin_bonus.parquet", _to_parquet(df_secret))

    allowed_map = {"hr_staff": hr_key}

    rows, cols, used, truncated = query_authorized_parquet_tables(
        sql="SELECT SUM(headcount) AS total_staff FROM hr_staff",
        allowed_tables_map=allowed_map,
        storage=store,
    )
    assert cols == ["total_staff"]
    assert rows == [(30,)]
    assert used == ["hr_staff"]
    assert truncated is False

    # Enforce row_limit + blocked external / cross-role access
    rows_lim, _, _, trunc_flag = query_authorized_parquet_tables(
        sql="SELECT headcount FROM hr_staff ORDER BY headcount",
        allowed_tables_map=allowed_map,
        storage=store,
        row_limit=1,
    )
    assert rows_lim == [(12,)]
    assert trunc_flag is True

    with pytest.raises((ValueError, duckdb.Error)):
        query_authorized_parquet_tables(
            sql="SELECT * FROM fin_bonus",
            allowed_tables_map=allowed_map,
            storage=store,
        )

    with pytest.raises((ValueError, duckdb.Error)):
        query_authorized_parquet_tables(
            sql=f"SELECT * FROM hr_staff, read_parquet('{fin_key}')",
            allowed_tables_map=allowed_map,
            storage=store,
        )


def test_docling_serve_parser_and_pdfplumber_fallback():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "document": {"md_content": "# Balance Sheet\n\n| Line | Value |\n| --- | --- |\n| Cash | $4M |"}
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_response
    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__.return_value = mock_client_instance

    parser = DoclingServePDFParser(base_url="http://docling-serve:5001", timeout_seconds=10)
    with patch("app.rag.processors.httpx.AsyncClient", return_value=mock_client_cm):
        docs = asyncio.run(parser.parse_bytes(b"%PDF-1.4 fake", "balance.pdf", "Finance"))

    assert len(docs) == 1
    assert docs[0].metadata["parser_used"] == "docling"
    assert docs[0].metadata["format"] == "markdown"
    assert "| Cash | $4M |" in docs[0].page_content

    # Simulate sidecar connection error -> must fall back cleanly to pdfplumber
    failing_client = AsyncMock()
    failing_client.post.side_effect = httpx.ConnectError("sidecar down")
    failing_cm = AsyncMock()
    failing_cm.__aenter__.return_value = failing_client

    with patch("app.rag.processors.httpx.AsyncClient", return_value=failing_cm), patch(
        "app.rag.processors.PDFDocumentLoader.load_bytes",
        return_value=[
            Document(
                page_content="--- Page 1 ---\nFallback parsed text",
                metadata={"role": "finance", "source": "balance.pdf", "parser_used": "pdfplumber"},
            )
        ],
    ) as mock_fb:
        fb_docs = asyncio.run(parser.parse_bytes(b"%PDF-1.4 fake", "balance.pdf", "Finance"))

    mock_fb.assert_called_once()
    assert fb_docs[0].metadata["parser_used"] == "pdfplumber"


def test_contextualizer_enrichment_and_offline_fallback():
    chunks = [
        Document(
            page_content="Employee PTO allocation is 20 days per year.",
            metadata={"role": "hr", "source": "handbook.md", "section_title": "Leave"},
        ),
        Document(
            page_content="Document Summary: handbook.md",
            metadata={"role": "hr", "source": "handbook.md", "chunk_type": "doc_summary"},
        ),
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text="This section of the 2026 HR handbook outlines annual paid time off entitlement."
    )

    enriched = asyncio.run(
        contextualize_chunks(
            chunks,
            full_text="# HR Handbook\n## Leave\nEmployee PTO allocation is 20 days per year.",
            filename="handbook.md",
            enabled=True,
            client_factory=lambda: mock_client,
        )
    )
    assert len(enriched) == 2
    assert enriched[0].page_content.startswith("Context: This section of the 2026 HR handbook")
    assert enriched[0].metadata["raw_content"] == "Employee PTO allocation is 20 days per year."
    assert enriched[1].page_content == "Document Summary: handbook.md"
    assert mock_client.models.generate_content.call_count == 1

    # Disabled contextualization uses deterministic fallback cleanly
    fallback_enriched = asyncio.run(
        contextualize_chunks(
            [chunks[0]],
            full_text="test",
            filename="handbook.md",
            enabled=False,
        )
    )
    assert "Document: handbook.md | Access Role: Hr | Section: Leave" in fallback_enriched[0].page_content


def test_gemini_embedding_2_service_prefixes_dimensions_and_retry():
    doc_with_title = Document(page_content="Quarterly EBITDA rose 14%.", metadata={"source": "q4.pdf"})
    doc_no_title = Document(page_content="General office note.", metadata={})
    assert format_document_for_embedding(doc_with_title) == "title: q4.pdf | text: Quarterly EBITDA rose 14%."
    assert format_document_for_embedding(doc_no_title) == "title: none | text: General office note."
    assert format_query_for_embedding("What was Q4 EBITDA?") == "task: question answering | query: What was Q4 EBITDA?"

    captured_calls: list[dict] = []
    attempt = 0

    def _mock_embed_content(*, model, contents, config):
        nonlocal attempt
        attempt += 1
        captured_calls.append({"model": model, "contents": contents, "config": config})
        if attempt == 1:
            raise RuntimeError("429 Resource Exhausted; retry in 0.01s")
        return MagicMock(
            embeddings=[MagicMock(values=[3.0, 4.0] + [0.0] * (1536 - 2)) for _ in contents]
        )

    fake_client = MagicMock()
    fake_client.models.embed_content.side_effect = _mock_embed_content

    svc = GeminiEmbedding2Service(
        model="gemini-embedding-2",
        dimensions=1536,
        client_factory=lambda: fake_client,
    )
    with patch("app.rag.embeddings.time.sleep"):
        vecs = svc.embed_documents([doc_with_title])

    assert len(vecs) == 1
    assert len(vecs[0]) == 1536
    # Normalized 3-4-5 vector
    assert math.isclose(vecs[0][0], 0.6, rel_tol=1e-5)
    assert math.isclose(vecs[0][1], 0.8, rel_tol=1e-5)
    assert captured_calls[-1]["config"].output_dimensionality == 1536
    assert captured_calls[-1]["contents"] == ["title: q4.pdf | text: Quarterly EBITDA rose 14%."]

    # Hard quota must raise immediately without retry sleeps
    quota_client = MagicMock()
    quota_client.models.embed_content.side_effect = RuntimeError("You exceeded your current quota.")
    svc_quota = GeminiEmbedding2Service(client_factory=lambda: quota_client)
    with pytest.raises(RuntimeError, match="quota"):
        svc_quota.embed_query("hello")
    assert quota_client.models.embed_content.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION B — Live PostgreSQL 17 + pgvector + Taskiq Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.postgres
def test_admin_user_and_role_crud_and_immediate_jwt_revocation(postgres_ready):
    admin_headers = _login("admin", "admin123")
    uid = uuid.uuid4().hex[:6]
    role_a = f"Legal_{uid}"
    role_b = f"Audit_{uid}"
    uname = f"crud_user_{uid}"

    try:
        assert client.post("/create-role", headers=admin_headers, data={"role_name": role_a}).status_code == 200
        assert client.post("/create-role", headers=admin_headers, data={"role_name": role_b}).status_code == 200
        assert (
            client.post(
                "/create-user",
                headers=admin_headers,
                data={"username": uname, "password": "initial-strong-password", "role": role_a},
            ).status_code
            == 200
        )

        users_res = client.get("/users", headers=admin_headers)
        assert users_res.status_code == 200
        user_rows = users_res.json()["users"]
        assert all("password" not in row and "password_hash" not in row for row in user_rows)
        assert any(row["username"] == uname and row["is_active"] is True for row in user_rows)

        # User logs in -> role change increments token_version -> old JWT rejected immediately
        user_token_1 = _login(uname, "initial-strong-password")
        assert client.get("/documents", headers=user_token_1).status_code == 200

        patch_res = client.patch(f"/users/{uname}", headers=admin_headers, json={"role": role_b})
        assert patch_res.status_code == 200
        assert patch_res.json()["role"] == role_b
        assert client.get("/documents", headers=user_token_1).status_code == 401

        # Fresh login succeeds; password reset immediately revokes token_2
        user_token_2 = _login(uname, "initial-strong-password")
        assert client.get("/documents", headers=user_token_2).status_code == 200
        reset_res = client.post(
            f"/users/{uname}/reset-password",
            headers=admin_headers,
            json={"password": "rotated-super-secret-password"},
        )
        assert reset_res.status_code == 200
        assert client.get("/documents", headers=user_token_2).status_code == 401
        assert client.get("/login", auth=(uname, "initial-strong-password")).status_code == 401

        # Deactivation blocks both existing JWT and fresh login
        user_token_3 = _login(uname, "rotated-super-secret-password")
        deact_res = client.patch(f"/users/{uname}", headers=admin_headers, json={"is_active": False})
        assert deact_res.status_code == 200
        assert deact_res.json()["is_active"] is False
        assert client.get("/documents", headers=user_token_3).status_code == 401
        assert client.get("/login", auth=(uname, "rotated-super-secret-password")).status_code == 401

        # Deleting an in-use role returns 409 Conflict; after deleting user it succeeds
        assert client.delete(f"/roles/{role_b}", headers=admin_headers).status_code == 409
        assert client.delete("/roles/C-Level", headers=admin_headers).status_code == 400
        assert client.delete("/roles/General", headers=admin_headers).status_code == 400

        # Self-lockout & self-deletion guards
        assert client.patch("/users/admin", headers=admin_headers, json={"is_active": False}).status_code == 400
        assert client.patch("/users/admin", headers=admin_headers, json={"role": "HR"}).status_code == 400
        assert client.delete("/users/admin", headers=admin_headers).status_code == 400

        assert client.delete(f"/users/{uname}", headers=admin_headers).status_code == 200
        assert client.delete(f"/roles/{role_a}", headers=admin_headers).status_code == 200
        assert client.delete(f"/roles/{role_b}", headers=admin_headers).status_code == 200
    finally:
        with sync_session() as db:
            db.execute(delete(User).where(User.username == uname))
            db.execute(delete(Role).where(Role.role_name.in_([role_a, role_b])))
            db.commit()


@pytest.mark.postgres
def test_document_crud_parquet_lifecycle_and_atomic_role_reassign(postgres_ready):
    from app.api import documents as docs_api

    admin_headers = _login("admin", "admin123")
    uid = uuid.uuid4().hex[:6]
    fname = f"rev_{uid}.csv"
    tname = f"rev_{uid}"
    csv_payload = b"quarter,revenue\nQ1,1200\nQ2,1450\n"

    orig_run = docs_api.run_indexer
    docs_api.run_indexer = lambda: None
    doc_id = None
    object_key = None
    parquet_key = None
    try:
        up = client.post(
            "/upload-docs",
            headers=admin_headers,
            data={"role": "Finance"},
            files={"file": (fname, csv_payload, "text/csv")},
        )
        assert up.status_code == 200, up.text
        doc_id = up.json()["doc_id"]
        object_key = up.json()["object_key"]

        storage = get_storage_backend()
        assert storage.exists(object_key) is True

        with sync_session() as db:
            tbl = db.scalar(select(DatasetTable).where(DatasetTable.doc_id == doc_id))
            assert tbl is not None
            assert tbl.table_name == tname
            assert tbl.row_count == 2
            parquet_key = tbl.parquet_key
        assert storage.exists(parquet_key) is True

        # Add a chunk & verify role reassignment updates Document, Chunk & DatasetTable atomically
        store = rag_module.get_hybrid_store()
        store.replace_document_chunks_sync(
            doc_id=doc_id,
            role="finance",
            source=fname,
            chunks=[Document(page_content="Q2 revenue grew strongly.", metadata={"role": "finance"})],
            vectors=[[0.1] * 1536],
        )

        patch_doc = client.patch(f"/documents/{doc_id}", headers=admin_headers, json={"role": "Marketing"})
        assert patch_doc.status_code == 200
        assert patch_doc.json()["role"] == "Marketing"

        with sync_session() as db:
            d_row = db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
            c_row = db.scalar(select(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
            t_row = db.scalar(select(DatasetTable).where(DatasetTable.doc_id == doc_id))
            assert d_row is not None and d_row.role == "Marketing"
            assert c_row is not None and c_row.role == "marketing"
            assert t_row is not None and t_row.role == "Marketing"

        # Single-doc reindex endpoint queues a durable JobRecord cleanly
        with patch("app.workers.tasks.index_document_task.kiq", new=AsyncMock()) as mock_kiq:
            reidx = client.post(f"/documents/{doc_id}/reindex", headers=admin_headers)
        assert reidx.status_code == 200
        job_id = reidx.json()["job_id"]
        mock_kiq.assert_called_once_with(job_id, doc_id)

        # Delete removes Postgres metadata, chunks, dataset table, and storage objects
        del_res = client.delete(f"/documents/{doc_id}", headers=admin_headers)
        assert del_res.status_code == 200
        assert storage.exists(object_key) is False
        assert storage.exists(parquet_key) is False
        with sync_session() as db:
            assert db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id)) is None
            assert db.scalar(select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)) is None
            assert db.scalar(select(DatasetTable).where(DatasetTable.doc_id == doc_id)) is None
            db.execute(delete(JobRecord).where(JobRecord.id == job_id))
            db.commit()
    finally:
        docs_api.run_indexer = orig_run


@pytest.mark.postgres
def test_durable_jobs_concurrency_lock_cancel_and_retry(postgres_ready):
    admin_headers = _login("admin", "admin123")
    with sync_session() as db:
        db.execute(delete(JobRecord).where(JobRecord.idempotency_key == "evaluation:active"))
        db.commit()

    created_job_ids: list[str] = []
    created_run_ids: list[str] = []
    try:
        with patch("app.api.evaluate.run_evaluation_task.kiq", new=AsyncMock()) as mock_eval_kiq:
            r1 = client.post("/evaluate", headers=admin_headers, json={"mode": "security_only"})
            assert r1.status_code == 200, r1.text
            job_id = r1.json()["job_id"]
            run_id = r1.json()["run_id"]
            created_job_ids.append(job_id)
            created_run_ids.append(run_id)
            mock_eval_kiq.assert_called_once()

            # Second concurrent /evaluate MUST be blocked by Postgres partial unique index -> 409
            r2 = client.post("/evaluate", headers=admin_headers, json={"mode": "full"})
            assert r2.status_code == 409

        # Cancel queued job immediately transitions queued -> cancelled
        c_res = client.post(f"/jobs/{job_id}/cancel", headers=admin_headers)
        assert c_res.status_code == 200
        assert c_res.json()["status"] == "cancelled"

        # Retrying a cancelled job creates a fresh durable job & dispatches task
        with patch("app.api.jobs.run_evaluation_task.kiq", new=AsyncMock()) as mock_retry_kiq:
            retry_res = client.post(f"/jobs/{job_id}/retry", headers=admin_headers)
            assert retry_res.status_code == 200, retry_res.text
            new_job_id = retry_res.json()["id"]
            created_job_ids.append(new_job_id)
            assert retry_res.json()["status"] == "queued"
            mock_retry_kiq.assert_called_once()
    finally:
        with sync_session() as db:
            db.execute(delete(EvaluationRun).where(EvaluationRun.job_id.in_(created_job_ids)))
            db.execute(delete(JobRecord).where(JobRecord.id.in_(created_job_ids)))
            db.commit()
