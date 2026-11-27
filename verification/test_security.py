"""Security & RBAC regression suite covering storage, SQL sandbox, and Postgres auth."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.append(str(Path(__file__).resolve().parent.parent))

_temporary = tempfile.TemporaryDirectory(prefix="finsight-security-")
_root = Path(_temporary.name)
(_root / "uploads").mkdir(parents=True, exist_ok=True)
os.environ.update(
    STORAGE_BACKEND="local",
    UPLOAD_DIR=str(_root / "uploads"),
    JWT_SECRET="offline-test-signing-secret-32-characters",
    APP_ENV="development",
    RATE_LIMIT_ENABLED="false",
)

from app.core.event_loop import ensure_selector_event_loop

ensure_selector_event_loop()

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, func, select, text

from app.api import admin, auth, documents
from app.core.limiter import limiter
from app.core.security import hash_password, verify_password
from app.core.sql_sandbox import query_authorized_tables
from app.db.models import DatasetTable, DocumentRecord, User
from app.db.session import get_sync_engine, sync_session
from app.storage import get_storage_backend, reset_storage_backend

limiter.enabled = False
reset_storage_backend()

api = FastAPI()
for router in (auth.router, documents.router, admin.router):
    api.include_router(router)
client = TestClient(api)

_POSTGRES_CHECKED: bool | None = None


def _ensure_postgres_security_db() -> bool:
    global _POSTGRES_CHECKED
    if _POSTGRES_CHECKED is not None:
        return _POSTGRES_CHECKED
    try:
        from alembic import command
        from alembic.config import Config
        from app.core.users import seed_default_users

        engine = get_sync_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            has_vec = conn.execute(
                text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            ).scalar()
            if not has_vec:
                _POSTGRES_CHECKED = False
                return False
        cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(cfg, "head")
        seed_default_users()
        _POSTGRES_CHECKED = True
    except Exception:
        _POSTGRES_CHECKED = False
    return _POSTGRES_CHECKED


@pytest.fixture
def pg_db():
    if not _ensure_postgres_security_db():
        pytest.skip(
            "PostgreSQL 17 with pgvector is unreachable; start 'docker compose up -d postgres' to run DB security tests."
        )
    return True


def headers(username: str = "admin", password: str = "admin123") -> dict[str, str]:
    response = client.get("/login", auth=(username, password))
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.mark.postgres
def test_regular_user_cannot_upload(pg_db):
    response = client.post(
        "/upload-docs",
        headers=headers("hr", "hr123"),
        data={"role": "Finance"},
        files={"file": ("forbidden.md", b"hello")},
    )
    assert response.status_code == 403
    assert not list((_root / "uploads").rglob("*forbidden.md"))


@pytest.mark.postgres
def test_role_names_are_case_insensitively_unique(pg_db):
    assert client.post("/create-role", headers=headers(), data={"role_name": "hR"}).status_code == 409
    assert client.post("/create-role", headers=headers(), data={"role_name": "../bad"}).status_code == 400


@pytest.mark.postgres
def test_new_users_require_strong_password_and_keep_whitespace(pg_db):
    uname = f"test_member_{uuid.uuid4().hex[:6]}"
    args = {"username": uname, "role": "HR", "password": "short"}
    assert client.post("/create-user", headers=headers(), data=args).status_code == 400
    args["password"] = " long-test-password "
    try:
        assert client.post("/create-user", headers=headers(), data=args).status_code == 200
        assert client.get("/login", auth=(uname, args["password"])).status_code == 200
        assert client.get("/login", auth=(uname, args["password"].strip())).status_code == 401
    finally:
        with sync_session() as db:
            db.execute(delete(User).where(User.username == uname))
            db.commit()


@pytest.mark.postgres
@pytest.mark.parametrize("filename", ["../escape.md", "..\\escape.md", "C:escape.md"])
def test_upload_rejects_path_traversal(pg_db, filename):
    response = client.post(
        "/upload-docs",
        headers=headers(),
        data={"role": "HR"},
        files={"file": (filename, b"hello")},
    )
    assert response.status_code == 400


@pytest.mark.postgres
def test_upload_rejects_unknown_role(pg_db):
    response = client.post(
        "/upload-docs",
        headers=headers(),
        data={"role": "../../outside"},
        files={"file": ("safe.md", b"hello")},
    )
    assert response.status_code == 400


@pytest.mark.postgres
def test_upload_rejects_oversize_file(pg_db):
    response = client.post(
        "/upload-docs",
        headers=headers(),
        data={"role": "HR"},
        files={"file": ("large.md", b"x" * (20 * 1024 * 1024 + 1))},
    )
    assert response.status_code == 413


@pytest.mark.postgres
def test_upload_rejects_empty_file(pg_db):
    response = client.post(
        "/upload-docs",
        headers=headers(),
        data={"role": "HR"},
        files={"file": ("empty.md", b"")},
    )
    assert response.status_code == 400


@pytest.mark.postgres
def test_duplicate_upload_does_not_overwrite(pg_db, monkeypatch):
    monkeypatch.setattr(documents, "run_indexer", lambda: None)
    fname = f"safe_{uuid.uuid4().hex[:6]}.md"
    args = dict(headers=headers(), data={"role": "HR"}, files={"file": (fname, b"original")})
    res1 = client.post("/upload-docs", **args)
    assert res1.status_code == 200, res1.text
    object_key = res1.json()["object_key"]
    doc_id = res1.json()["doc_id"]
    try:
        args["files"] = {"file": (fname, b"changed")}
        assert client.post("/upload-docs", **args).status_code == 409
        assert get_storage_backend().get_bytes(object_key) == b"original"
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.commit()
        get_storage_backend().delete(object_key)


@pytest.mark.postgres
def test_pdf_requires_department_authorization(pg_db):
    storage = get_storage_backend()
    obj_key = storage.put_bytes(
        f"documents/Finance/{uuid.uuid4().hex}_private.pdf",
        b"%PDF-1.4 test",
        content_type="application/pdf",
    )
    legacy_path = str((_root / "uploads" / f"{uuid.uuid4().hex}_private.pdf").resolve())
    with sync_session() as db:
        doc = DocumentRecord(
            filename="private.pdf",
            role="Finance",
            object_key=obj_key,
            legacy_filepath=legacy_path,
            content_type="application/pdf",
            size_bytes=13,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    try:
        assert client.get("/preview-pdf", params={"filepath": legacy_path}, headers=headers("hr", "hr123")).status_code == 403
        allowed = client.get("/preview-pdf", params={"filepath": legacy_path}, headers=headers("finance", "finance123"))
        assert allowed.status_code == 200
        assert allowed.headers["cache-control"] == "no-store"

        allowed_by_id = client.get("/preview-pdf", params={"doc_id": doc_id}, headers=headers("finance", "finance123"))
        assert allowed_by_id.status_code == 200
        assert client.get("/preview-pdf", params={"filepath": legacy_path, "token": headers()["Authorization"][7:]}).status_code in (401, 403)
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.commit()
        storage.delete(obj_key)


@pytest.mark.postgres
def test_unregistered_pdf_is_denied_even_inside_uploads(pg_db):
    path = _root / "uploads" / "unregistered.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    assert client.get("/preview-pdf", params={"filepath": str(path)}, headers=headers()).status_code == 403


@pytest.mark.postgres
def test_registered_noncanonical_path_remains_accessible(pg_db):
    storage = get_storage_backend()
    obj_key = storage.put_bytes(
        f"documents/HR/{uuid.uuid4().hex}_alias.md",
        b"Authorized content",
        content_type="text/markdown",
    )
    registered = str(_root / "uploads" / "nested" / ".." / "nested" / f"{uuid.uuid4().hex}_alias.md")
    with sync_session() as db:
        doc = DocumentRecord(
            filename="alias.md",
            role="HR",
            object_key=obj_key,
            legacy_filepath=registered,
            content_type="text/markdown",
            size_bytes=18,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    try:
        response = client.get("/documents/content", params={"filepath": registered}, headers=headers("hr", "hr123"))
        assert response.status_code == 200 and response.json()["content"] == "Authorized content"
        by_id = client.get("/documents/content", params={"doc_id": doc_id}, headers=headers("hr", "hr123"))
        assert by_id.status_code == 200 and by_id.json()["content"] == "Authorized content"
        assert client.get("/documents/content", params={"filepath": registered}, headers=headers("finance", "finance123")).status_code == 403
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.commit()
        storage.delete(obj_key)


@pytest.mark.postgres
def test_changed_role_and_token_version_invalidate_old_token(pg_db):
    token = headers("marketing", "marketing123")
    with sync_session() as db:
        user = db.scalar(select(User).where(User.username == "marketing"))
        assert user is not None
        user.role_name = "General"
        db.commit()
    try:
        assert client.get("/documents", headers=token).status_code == 401
    finally:
        with sync_session() as db:
            user = db.scalar(select(User).where(User.username == "marketing"))
            if user is not None:
                user.role_name = "Marketing"
                db.commit()


@pytest.mark.postgres
def test_seed_does_not_reset_existing_password(pg_db):
    from app.core.users import seed_default_users

    with sync_session() as db:
        user = db.scalar(select(User).where(User.username == "engineering"))
        assert user is not None
        orig_hash = user.password_hash
        user.password_hash = hash_password("updated-secret")
        db.commit()
    try:
        seed_default_users()
        with sync_session() as db:
            stored = db.scalar(select(User.password_hash).where(User.username == "engineering"))
        assert stored is not None and verify_password("updated-secret", stored)
    finally:
        with sync_session() as db:
            user = db.scalar(select(User).where(User.username == "engineering"))
            if user is not None:
                user.password_hash = orig_hash
                db.commit()


@pytest.fixture
def sql_database(tmp_path):
    path = str(tmp_path / "query.duckdb")
    conn = duckdb.connect(path)
    conn.execute("CREATE TABLE allowed AS SELECT 1 AS amount")
    conn.execute("CREATE TABLE private AS SELECT 999 AS amount")
    conn.close()
    return path


def test_authorized_sql_and_row_limit(sql_database):
    rows, columns, sources, truncated = query_authorized_tables(sql_database, "SELECT * FROM allowed", ["allowed"])
    assert rows == [(1,)] and columns == ["amount"] and sources == ["allowed"] and not truncated
    rows, _, _, truncated = query_authorized_tables(
        sql_database,
        "SELECT a.amount FROM allowed a CROSS JOIN range(20)",
        ["allowed"],
        row_limit=5,
    )
    assert len(rows) == 5 and truncated


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM allowed, private",
        "SELECT * FROM allowed JOIN private ON true",
        "SELECT * FROM allowed WHERE EXISTS (SELECT 1 FROM private)",
        "SELECT * FROM allowed; SELECT * FROM private",
        "DELETE FROM allowed",
        "SELECT * FROM read_csv_auto('/private.csv')",
        "SELECT * FROM allowed, read_csv_auto('https://example.com/data.csv')",
    ],
)
def test_sql_cannot_escape_authorized_snapshot(sql_database, sql):
    with pytest.raises((ValueError, duckdb.Error)):
        query_authorized_tables(sql_database, sql, ["allowed"])
