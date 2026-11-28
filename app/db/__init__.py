"""
app/db/__init__.py — PostgreSQL 17 + pgvector ORM models and session helpers.
"""

from app.db.models import (
    Base,
    DatasetTable,
    DocumentChunk,
    DocumentRecord,
    EvaluationRun,
    JobRecord,
    Role,
    User,
)
from app.db.session import (
    async_session,
    close_db_engines,
    get_async_engine,
    get_async_session_factory,
    get_db,
    get_sync_engine,
    get_sync_session_factory,
    reset_db_engines,
    sync_session,
)

__all__ = [
    "Base",
    "Role",
    "User",
    "DocumentRecord",
    "DocumentChunk",
    "DatasetTable",
    "JobRecord",
    "EvaluationRun",
    "async_session",
    "sync_session",
    "get_db",
    "get_async_engine",
    "get_async_session_factory",
    "get_sync_engine",
    "get_sync_session_factory",
    "close_db_engines",
    "reset_db_engines",
]
