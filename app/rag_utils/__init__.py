"""
app/rag_utils/__init__.py — Backward-compatibility shims.

The old `app/rag_utils/` package has been superseded by:
  - app/rag/           — RAG engine, classifier, CSV query, processors
  - app/core/config.py — key & settings management

These shims keep any external scripts or notebooks that still import
from `app.rag_utils.*` working without modification.
"""

# Silence the deprecation notice by re-exporting from the new packages.
from app.rag.module     import get_rag_chain, run_indexer          # noqa: F401
from app.rag.chain      import ask_rag                             # noqa: F401
from app.rag.csv_query  import ask_csv                             # noqa: F401
from app.rag.classifier import detect_query_type_llm               # noqa: F401
from app.core.config    import (                                   # noqa: F401
    google_api_key, langchain_key, cohere_api_key,
    generate_content_with_fallback,
)
