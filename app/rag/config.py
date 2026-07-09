"""
app/rag/config.py — RAG-specific configuration.

Reads app/core/config.py settings and applies them to LangSmith tracing
and the Google / Cohere API key environment variables.  Import this module
before any LangChain imports to ensure env-vars are set correctly.
"""

import os
from app.core.config import google_api_key, langchain_key, cohere_api_key

# ── LangSmith tracing (optional) ──────────────────────────────────────────────
if langchain_key.strip() and "your_langchain_api_key" not in langchain_key.lower():
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"]   = "https://api.smith.langchain.com"
    os.environ["LANGCHAIN_PROJECT"]    = "RAG"
    os.environ["LANGCHAIN_API_KEY"]    = langchain_key
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

os.environ["GOOGLE_API_KEY"] = google_api_key
os.environ["COHERE_API_KEY"] = cohere_api_key
