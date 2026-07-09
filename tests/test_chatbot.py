import sys
from pathlib import Path

# Add root directory to Python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from app.main import app
import io
from unittest.mock import patch

client = TestClient(app)

@pytest.fixture
def c_level_headers():
    res = client.get("/login", auth=("admin", "admin123"))
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def regular_headers():
    res = client.get("/login", auth=("hr", "hr123"))
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_create_role_c_level(c_level_headers):
    res = client.post("/create-role", headers=c_level_headers, data={"role_name": "engineering"})
    assert res.status_code == 200
    assert "Role 'engineering' created" in res.json().get("message", "")

def test_create_user_c_level(c_level_headers):
    # First ensure the role exists
    client.post("/create-role", headers=c_level_headers, data={"role_name": "marketing"})

    res = client.post(
        "/create-user",
        headers=c_level_headers,
        data={
            "username": "newuser",
            "password": "newpass",
            "role": "marketing"
        }
    )
    assert res.status_code == 200
    assert "User 'newuser'" in res.json().get("message", "")

@patch("app.api.documents.run_indexer")
def test_upload_csv_doc(mock_run_indexer, c_level_headers):
    content = b"Name,Policy\nAdmin,Compliant"
    file = io.BytesIO(content)
    client.post("/create-role", headers=c_level_headers, data={"role_name": "csvrole"})

    res = client.post(
        "/upload-docs",
        headers=c_level_headers,
        files={"file": ("test.csv", file, "text/csv")},
        data={"role": "csvrole"}
    )

    assert res.status_code == 200
    assert "uploaded" in res.json()["message"]

@patch("app.api.documents.run_indexer")
def test_upload_md_doc(mock_run_indexer, c_level_headers):
    content = b"# Engineering Policies\nFollow coding guidelines."
    file = io.BytesIO(content)
    client.post("/create-role", headers=c_level_headers, data={"role_name": "mdrole"})

    res = client.post(
        "/upload-docs",
        headers=c_level_headers,
        files={"file": ("guide.md", file, "text/markdown")},
        data={"role": "mdrole"}
    )

    assert res.status_code == 200
    assert "uploaded" in res.json()["message"]

@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "This is RAG response"})
def test_chat_rag_mode(mock_ask_rag, mock_detect, c_level_headers):
    res = client.post(
        "/chat",
        headers=c_level_headers,
        json={"question": "What are engineering policies?"}
    )
    assert res.status_code == 200
    assert res.json()["mode"] == "RAG"
    assert res.json()["answer"] == "This is RAG response"

@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "Here is the SQL data", "sql": "SELECT * FROM table"})
def test_chat_sql_mode(mock_ask_csv, mock_detect, c_level_headers):
    res = client.post(
        "/chat",
        headers=c_level_headers,
        json={"question": "List all employees in HR"}
    )
    assert res.status_code == 200
    assert res.json()["mode"] == "SQL"
    assert res.json()["answer"] == "Here is the SQL data"
    assert "sql" in res.json()

def test_create_role_no_auth():
    res = client.post("/create-role", data={"role_name": "bad"})
    assert res.status_code == 401 or res.status_code == 403

@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag")
def test_chat_rag_blocks_cross_role(mock_ask_rag, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": "What is in the finance data?"}
    )
    assert res.status_code == 200
    assert "Access Restricted" in res.json()["answer"]
    mock_ask_rag.assert_not_called()

@patch("app.api.chat.detect_query_type_llm", return_value="RAG")
@patch("app.api.chat.ask_rag", return_value={"answer": "policies"})
def test_chat_rag_role_passed(mock_ask_rag, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": "What are company policies?"}
    )
    assert res.status_code == 200
    mock_ask_rag.assert_called_once_with("What are company policies?", "HR")

@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv")
def test_chat_sql_blocks_cross_role(mock_ask_csv, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": "List finance data"}
    )
    assert res.status_code == 200
    assert "Access Restricted" in res.json()["answer"]
    mock_ask_csv.assert_not_called()

@patch("app.api.chat.detect_query_type_llm", return_value="SQL")
@patch("app.api.chat.ask_csv", return_value={"answer": "data"})
def test_chat_sql_role_passed(mock_ask_csv, mock_detect, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": "Show my records"}
    )
    assert res.status_code == 200
    mock_ask_csv.assert_called_once_with("Show my records", "HR", "hr", return_sql=True)

@patch("app.api.chat.ask_rag", return_value={"answer": "No documents found for your role."})
def test_chat_rag_returns_nothing_for_unmatched_docs(mock_ask_rag, regular_headers):
    res = client.post(
        "/chat",
        headers=regular_headers,
        json={"question": "Tell me about executive bonuses"}
    )
    assert res.status_code == 200
    assert "no documents found" in res.json()["answer"].lower()
