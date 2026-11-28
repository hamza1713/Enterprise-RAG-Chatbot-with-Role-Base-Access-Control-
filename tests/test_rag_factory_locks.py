"""
tests/test_rag_factory_locks.py — Regression guard for the lazy RAG singletons.

get_hybrid_store() used to call get_embeddings_service() while holding the same
non-reentrant lock, so the first call on a cold process deadlocked forever.
"""

from __future__ import annotations

import threading

import app.rag.module as rag_module


class _FakeEmbeddings:
    pass


class _FakeStore:
    def __init__(self, embeddings):
        self.embeddings = embeddings


def test_cold_get_hybrid_store_does_not_deadlock(monkeypatch):
    monkeypatch.setattr(rag_module, "embeddings_service", None)
    monkeypatch.setattr(rag_module, "hybrid_store", None)
    monkeypatch.setattr(rag_module, "GeminiEmbedding2Service", _FakeEmbeddings)
    monkeypatch.setattr(rag_module, "PgVectorHybridStore", _FakeStore)

    result: dict[str, object] = {}
    worker = threading.Thread(
        target=lambda: result.setdefault("store", rag_module.get_hybrid_store()),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive(), "get_hybrid_store() deadlocked on a cold start"
    store = result["store"]
    assert isinstance(store, _FakeStore)
    assert store.embeddings is rag_module.embeddings_service
    assert rag_module.get_hybrid_store() is store
