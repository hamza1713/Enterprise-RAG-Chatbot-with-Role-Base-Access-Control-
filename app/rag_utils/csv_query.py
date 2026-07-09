"""
app/rag_utils/csv_query.py — Deprecated shim.

All logic has moved to app.rag.csv_query.
"""
from app.rag.csv_query import (  # noqa: F401
    ask_csv,
    get_allowed_tables_for_role,
    translate_nl_to_sql,
    is_safe_query,
    extract_tables_from_sql,
)
