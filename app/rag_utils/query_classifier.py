"""
app/rag_utils/query_classifier.py — Deprecated shim.

All logic has moved to app.rag.classifier.
"""
from app.rag.classifier import detect_query_type_llm  # noqa: F401
