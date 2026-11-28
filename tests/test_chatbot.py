"""Chatbot & Upload integration tests backed by PostgreSQL + ObjectStorageBackend."""

from __future__ import annotations

import io
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete

from app.db.models import DocumentRecord, Role, User
from app.db.session import sync_session
from app.main import app
from app.storage import get_storage_backend

client = TestClient(app)


@pytest.fixture
def c_level_headers(postgres_ready):
    res = client.get("/login", auth=("admin", "admin123"))
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def regular_headers(postgres_ready):
    res = client.get("/login", auth=("hr", "hr123"))
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.postgres
def test_create_role_c_level(c_level_headers):
    rname = f"support_ops_{uuid.uuid4().hex[:6]}"
    try:
        res = client.post("/create-role", headers=c_level_headers, data={"role_name": rname})
        assert res.status_code == 200
        assert f"Role '{rname}' created" in res.json().get("message", "")
    finally:
        with sync_session() as db:
            db.execute(delete(Role).where(Role.role_name == rname))
            db.commit()


@pytest.mark.postgres
def test_create_user_c_level(c_level_headers):
    uname = f"newuser_{uuid.uuid4().hex[:6]}"
    try:
        res = client.post(
            "/create-user",
            headers=c_level_headers,
            data={
                "username": uname,
                "password": "new-password-for-test",
                "role": "Marketing",
            },
        )
        assert res.status_code == 200
        assert f"User '{uname}'" in res.json().get("message", "")
    finally:
        with sync_session() as db:
            db.execute(delete(User).where(User.username == uname))
            db.commit()


@pytest.mark.postgres
@patch("app.api.documents.run_indexer")
def test_upload_csv_doc(mock_run_indexer, c_level_headers):
    uid = uuid.uuid4().hex[:6]
    fname = f"test_{uid}.csv"
    content = b"Name,Policy\nAdmin,Compliant"
    file = io.BytesIO(content)
    res = client.post(
        "/upload-docs",
        headers=c_level_headers,
        files={"file": (fname, file, "text/csv")},
        data={"role": "HR"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "uploaded" in body["message"]
    try:
        mock_run_indexer.assert_called_once()
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == body["doc_id"]))
            db.commit()
        get_storage_backend().delete(body["object_key"])


@pytest.mark.postgres
@patch("app.api.documents.run_indexer")
def test_upload_md_doc(mock_run_indexer, c_level_headers):
    uid = uuid.uuid4().hex[:6]
    fname = f"guide_{uid}.md"
    content = b"# Engineering Policies\nFollow coding guidelines."
    file = io.BytesIO(content)
    res = client.post(
        "/upload-docs",
        headers=c_level_headers,
        files={"file": (fname, file, "text/markdown")},
        data={"role": "Engineering"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "uploaded" in body["message"]
    try:
        mock_run_indexer.assert_called_once()
    finally:
        with sync_session() as db:
            db.execute(delete(DocumentRecord).where(DocumentRecord.id == body["doc_id"]))
            db.commit()
        get_storage_backend().delete(body["object_key"])


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "This is RAG response"})
def test_chat_rag_mode(mock_ask_rag, mock_detect, c_level_headers):
    res = client.post(
        "/chat",
        headers=c_level_headers,
        json={"question": f"What are engineering policies {uuid.uuid4().hex[:6]}?"},
    )
    assert res.status_code == 200
    assert res.json()["mode"] == "RAG"
    assert res.json()["answer"] == "This is RAG response"


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "Here is the SQL data", "sql": "SELECT * FROM table"})
def test_chat_sql_mode(mock_ask_csv, mock_detect, c_level_headers):
    res = client.post(
        "/chat",
        headers=c_level_headers,
        json={"question": f"List all employees in HR {uuid.uuid4().hex[:6]}"},
    )
    assert res.status_code == 200
    assert res.json()["mode"] == "SQL"
    assert res.json()["answer"] == "Here is the SQL data"
    assert "sql" in res.json()


def test_create_role_no_auth():
    # Fresh client: the shared one holds an admin session cookie from earlier logins.
    anonymous = TestClient(app)
    res = anonymous.post("/create-role", data={"role_name": "bad"})
    assert res.status_code in (401, 403)


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "I could not find relevant information about this topic in your accessible documents.", "sources": []})
def test_chat_rag_allows_query_and_enforces_rebac_isolation(mock_ask_rag, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": f"What is in the finance data {uuid.uuid4().hex[:6]}?"},
    )
    assert res.status_code == 200
    assert "Access Restricted" not in res.json()["answer"]
    mock_ask_rag.assert_called_once()


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "policies"})
def test_chat_rag_role_passed(mock_ask_rag, mock_detect, regular_headers):
    q = f"What are company policies {uuid.uuid4().hex[:6]}?"
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": q},
    )
    assert res.status_code == 200
    mock_ask_rag.assert_called_once_with(q, "HR")


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "You do not have access to any structured datasets matching this query.", "sources": []})
def test_chat_sql_enforces_rebac_without_phrase_blocklist(mock_ask_csv, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": f"List finance data {uuid.uuid4().hex[:6]}"},
    )
    assert res.status_code == 200
    assert "Access Restricted" not in res.json()["answer"]
    mock_ask_csv.assert_called_once()


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "data"})
def test_chat_sql_role_passed(mock_ask_csv, mock_detect, regular_headers):
    q = f"Show my records {uuid.uuid4().hex[:6]}"
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": q},
    )
    assert res.status_code == 200
    mock_ask_csv.assert_called_once_with(q, "HR", "hr", return_sql=True)


@pytest.mark.postgres
@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "No documents found for your role."})
def test_chat_rag_returns_nothing_for_unmatched_docs(mock_ask_rag, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": f"Tell me about executive bonuses {uuid.uuid4().hex[:6]}"},
    )
    assert res.status_code == 200
    assert "no documents found" in res.json()["answer"].lower()
