"""
tests/test_phase2_rebac.py — OpenFGA ReBAC evaluation, client mocking, and pgvector pre/post filtering.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.authz.openfga import FINSIGHT_FGA_MODEL_DICT, ReBACService, normalize_subject
from app.core.config import EMBEDDING_DIMENSIONS
from app.rag.pgvector_store import PgVectorHybridStore, build_hybrid_rrf_sql


def _t(subject: str, relation: str, object_type: str, object_id: str):
    return SimpleNamespace(
        subject=subject,
        relation=relation,
        object_type=object_type,
        object_id=object_id,
    )


def test_normalize_subject_and_canonical_fga_model():
    assert normalize_subject("User:Alice") == "user:alice"
    assert normalize_subject("role:Finance") == "role:finance#assignee"
    assert normalize_subject("role:hr#assignee") == "role:hr#assignee"
    assert normalize_subject("folder:m_and_a") == "folder:m_and_a#member"

    type_names = [td["type"] for td in FINSIGHT_FGA_MODEL_DICT["type_definitions"]]
    assert type_names == ["user", "role", "folder", "document", "dataset"]


def test_pg_rebac_mirror_handles_per_user_sharing_and_folder_inheritance():
    tuples = [
        _t("user:alice", "assignee", "role", "engineering"),
        _t("user:alice", "assignee", "role", "general"),
        _t("user:bob", "assignee", "role", "engineering"),
        _t("user:bob", "assignee", "role", "general"),
        _t("user:carol", "assignee", "role", "finance"),
        # doc 1 = Engineering, doc 2 = General, doc 3 = Finance (shared directly to user:alice!), doc 4 = M&A folder
        _t("role:engineering", "parent_role", "document", "1"),
        _t("role:c-level", "admin_role", "document", "1"),
        _t("role:general", "parent_role", "document", "2"),
        _t("role:finance", "parent_role", "document", "3"),
        _t("user:alice", "viewer", "document", "3"),
        _t("folder:ma_deal", "member", "folder", "ma_deal"),  # irrelevant self
        _t("role:finance#assignee", "member", "folder", "ma_deal"),
        _t("folder:ma_deal", "parent_folder", "document", "4"),
        _t("role:hr", "parent_role", "document", "4"),
    ]
    all_docs = [(1, "Engineering"), (2, "General"), (3, "Finance"), (4, "HR")]

    alice_docs = ReBACService._eval_pg_authorized_doc_ids_rows(
        "alice", "Engineering", tuples, all_docs
    )
    bob_docs = ReBACService._eval_pg_authorized_doc_ids_rows(
        "bob", "Engineering", tuples, all_docs
    )
    carol_docs = ReBACService._eval_pg_authorized_doc_ids_rows(
        "carol", "Finance", tuples, all_docs
    )

    assert alice_docs == [1, 2, 3]
    assert bob_docs == [1, 2]  # Same role as alice, does NOT see doc 3!
    assert carol_docs == [2, 3, 4]  # Sees General(2), Finance(3), and folder-inherited doc(4)


def test_openfga_client_list_objects_and_batch_check():
    svc = ReBACService(
        api_url="http://openfga:8080",
        store_name="finsight",
        store_id="store-123",
        model_id="model-456",
    )

    fake_client = AsyncMock()
    fake_client.list_objects.return_value = SimpleNamespace(
        objects=["document:10", "document:25"]
    )
    fake_client.batch_check.return_value = SimpleNamespace(
        result=[
            SimpleNamespace(correlation_id="0", allowed=True),
            SimpleNamespace(correlation_id="1", allowed=False),  # Revoked mid-flight!
        ]
    )
    fake_cm = AsyncMock()
    fake_cm.__aenter__.return_value = fake_client

    with patch.object(svc, "_create_fga_client", return_value=fake_cm):
        listed = asyncio.run(svc.alist_authorized_doc_ids(username="alice", user_role="Engineering"))
        verified = asyncio.run(
            svc.abatch_filter_doc_ids(
                username="alice", user_role="Engineering", candidate_doc_ids=[10, 25]
            )
        )

    assert listed == [10, 25]
    assert verified == {10}


def test_pgvector_rrf_sql_enforces_doc_id_prefilter_in_both_ctes():
    sql_str, params = build_hybrid_rrf_sql(
        "Engineering", include_sparse=True, allowed_doc_ids=[7, 3, 7]
    )
    assert params["allowed_doc_ids"] == [3, 7]
    # Predicate must appear in both dense CTE and sparse CTE
    assert sql_str.count("doc_id = ANY(:allowed_doc_ids)") == 2

    mock_emb = MagicMock()
    mock_emb.embed_query.return_value = [0.0] * EMBEDDING_DIMENSIONS
    mock_emb.aembed_query = AsyncMock(return_value=[0.0] * EMBEDDING_DIMENSIONS)
    store = PgVectorHybridStore(embeddings=mock_emb)

    # Empty allowed_doc_ids must short-circuit cleanly without calling embeddings
    empty_res = asyncio.run(
        store.asearch("revenue", "General", allowed_doc_ids=[])
    )
    assert empty_res == []
    mock_emb.aembed_query.assert_not_called()
