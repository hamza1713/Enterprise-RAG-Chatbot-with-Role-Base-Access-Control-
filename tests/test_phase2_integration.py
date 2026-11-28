"""
tests/test_phase2_integration.py — Live PostgreSQL 17 + OpenFGA Phase 2 integration checks.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import delete, inspect

from app.agents.graph import init_agent_runtime, shutdown_agent_runtime
from app.authz.openfga import ReBACService
from app.core.config import get_database_url
from app.db.models import ChatThread, DocumentRecord, SemanticModel, User
from app.db.session import get_sync_engine, sync_session
from app.main import app
from app.storage import get_storage_backend

client = TestClient(app)


def _bearer_headers(username: str, password: str) -> dict[str, str]:
    res = client.get("/login", auth=(username, password))
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.postgres
def test_alembic_0002_tables_and_langgraph_checkpointer_setup(postgres_ready):
    engine = get_sync_engine()
    tables = set(inspect(engine).get_table_names())
    assert {"acl_tuples", "chat_threads", "chat_messages", "semantic_models"}.issubset(tables)

    async def _boot():
        await init_agent_runtime()
        await shutdown_agent_runtime()

    asyncio.run(_boot())
    tables_after = set(inspect(engine).get_table_names())
    assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"}.issubset(tables_after)


@pytest.mark.postgres
@patch("app.api.documents.run_indexer")
def test_per_user_rebac_sharing_and_threads_persistence(mock_indexer, postgres_ready):
    admin_hdrs = _bearer_headers("admin", "admin123")
    uid = uuid.uuid4().hex[:6]
    alice = f"alice_{uid}"
    bob = f"bob_{uid}"
    doc_name = f"secret_board_{uid}.md"

    doc_id: int | None = None
    obj_key: str | None = None
    thread_id: str | None = None

    try:
        # Two users inside Engineering department
        for uname in (alice, bob):
            r = client.post(
                "/create-user",
                headers=admin_hdrs,
                data={"username": uname, "password": "strong-user-password", "role": "Engineering"},
            )
            assert r.status_code == 200, r.text

        # Upload Finance-restricted document
        up = client.post(
            "/upload-docs",
            headers=admin_hdrs,
            data={"role": "Finance"},
            files={"file": (doc_name, b"# Executive Deal Memo\nProject Phoenix details.", "text/markdown")},
        )
        assert up.status_code == 200, up.text
        doc_id = up.json()["doc_id"]
        obj_key = up.json()["object_key"]

        alice_hdrs = _bearer_headers(alice, "strong-user-password")
        bob_hdrs = _bearer_headers(bob, "strong-user-password")

        # Initially neither Alice nor Bob sees Finance doc
        assert all(d["id"] != doc_id for d in client.get("/documents", headers=alice_hdrs).json())
        assert all(d["id"] != doc_id for d in client.get("/documents", headers=bob_hdrs).json())

        # Grant direct viewer tuple ONLY to user:alice
        grant = client.post(
            f"/documents/{doc_id}/permissions",
            headers=admin_hdrs,
            json={"subject": f"user:{alice}", "relation": "viewer"},
        )
        assert grant.status_code == 200, grant.text

        # Alice now sees doc_id, Bob in exact same role STILL does NOT!
        assert any(d["id"] == doc_id for d in client.get("/documents", headers=alice_hdrs).json())
        assert all(d["id"] != doc_id for d in client.get("/documents", headers=bob_hdrs).json())

        # Revoke permission -> Alice loses access immediately
        rev = client.delete(
            f"/documents/{doc_id}/permissions",
            headers=admin_hdrs,
            params={"subject": f"user:{alice}", "relation": "viewer"},
        )
        assert rev.status_code == 200
        assert all(d["id"] != doc_id for d in client.get("/documents", headers=alice_hdrs).json())

        # Persistent conversation thread CRUD + ownership
        created_thread = client.post(
            "/threads", headers=alice_hdrs, json={"title": "My Audit"}
        )
        assert created_thread.status_code == 200
        thread_id = created_thread.json()["id"]
        assert client.get(f"/threads/{thread_id}", headers=bob_hdrs).status_code == 404
        assert client.get(f"/threads/{thread_id}", headers=alice_hdrs).status_code == 200
    finally:
        with sync_session() as db:
            if thread_id:
                db.execute(delete(ChatThread).where(ChatThread.id == thread_id))
            if doc_id is not None:
                db.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))
            db.execute(delete(User).where(User.username.in_([alice, bob])))
            db.commit()
        if obj_key:
            get_storage_backend().delete(obj_key)


@pytest.mark.postgres
def test_live_openfga_sidecar_roundtrip_if_running(postgres_ready):
    fga_url = os.getenv("OPENFGA_API_URL", "").strip().rstrip("/")
    if not fga_url:
        pytest.skip("OPENFGA_API_URL not set; skipping live OpenFGA HTTP test.")
    try:
        resp = httpx.get(f"{fga_url}/healthz", timeout=2.0)
        if resp.status_code >= 400:
            pytest.skip("OpenFGA sidecar not healthy.")
    except Exception:
        pytest.skip("OpenFGA sidecar unreachable.")

    svc = ReBACService(api_url=fga_url, store_name=f"finsight_test_{uuid.uuid4().hex[:6]}")
    uid = uuid.uuid4().hex[:6]
    u = f"fga_{uid}"

    async def _roundtrip():
        sid, mid = await svc.aensure_store_and_model()
        assert sid and mid
        await svc._push_fga_mutations(
            writes=[
                (f"user:{u}", "assignee", "role", "engineering"),
                ("role:engineering", "parent_role", "document", "999001"),
                (f"user:{u}", "viewer", "document", "999002"),
            ]
        )
        listed = await svc._fga_list_objects(u, "document")
        checked = await svc._fga_batch_check(u, "document", ["999001", "999002", "999003"])
        return listed, checked

    listed, checked = asyncio.run(_roundtrip())
    assert set(listed or []) >= {"999001", "999002"}
    assert "999003" not in (listed or [])
    assert checked == {"999001", "999002"}
