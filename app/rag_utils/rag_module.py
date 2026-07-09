"""
app/rag_utils/rag_module.py — Deprecated shim.

All logic has moved to app.rag.module.
"""
from app.rag.module import (  # noqa: F401
    get_rag_chain,
    run_indexer,
    trigger_indexing,
    trigger_retry_pending,
    start_indexer_worker,
    HybridMultiQueryRetriever,
    RetryingEmbeddings,
    build_system_prompt,
    expand_query,
    vectorstore,
    google_embeddings,
    _reset_databases,
    _reinit_vectorstore,
)