"""
app/rag_utils/secret_key.py — Deprecated: use app.core.config instead.

Kept as a shim so any code that still does:
  from app.rag_utils.secret_key import google_api_key
continues to work without modification.
"""

import warnings
warnings.warn(
    "app.rag_utils.secret_key is deprecated. Import from app.core.config instead.",
    DeprecationWarning,
    stacklevel=2,
)

from app.core.config import (  # noqa: F401
    google_api_key,
    openapi_key,
    langchain_key,
    cohere_api_key,
    generate_content_with_fallback,
)
