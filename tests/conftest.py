"""Keep every test store separate from developer documents and indexes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

import pytest

from app.core.event_loop import ensure_selector_event_loop

ensure_selector_event_loop()

TEST_ROOT = Path(tempfile.mkdtemp(prefix="finsight-tests-"))
os.environ.update(
    {
        "APP_ENV": "development",
        "STORAGE_BACKEND": "local",
        "UPLOAD_DIR": str(TEST_ROOT / "uploads"),
        "EVAL_OUTPUT_DIR": str(TEST_ROOT / "evaluation"),
        "JWT_SECRET": "offline-test-signing-secret-at-least-32-characters",
        "GOOGLE_API_KEY": "offline-test-key",
        "COHERE_API_KEY": "",
        "LANGCHAIN_API_KEY": "",
        "RATE_LIMIT_ENABLED": "false",
    }
)


_POSTGRES_READY: bool | None = None


def ensure_postgres_test_env() -> bool:
    """
    Check if PostgreSQL + pgvector is reachable at DATABASE_URL / TEST_DATABASE_URL.
    When reachable, apply Alembic migrations idempotently and seed default users/roles.
    """
    global _POSTGRES_READY
    if _POSTGRES_READY is not None:
        return _POSTGRES_READY

    try:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        from app.core.users import seed_default_users
        from app.db.session import get_sync_engine

        engine = get_sync_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            has_vec = conn.execute(
                text(
                    "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
                )
            ).scalar()
            if not has_vec:
                _POSTGRES_READY = False
                return False

        cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(cfg, "head")
        seed_default_users()
        _POSTGRES_READY = True
    except Exception:
        _POSTGRES_READY = False

    return _POSTGRES_READY


@pytest.fixture(scope="session")
def postgres_ready() -> bool:
    """Skip Postgres-dependent tests gracefully when no pgvector Postgres instance is running."""
    if not ensure_postgres_test_env():
        pytest.skip(
            "PostgreSQL 17 with pgvector extension is unreachable at DATABASE_URL/TEST_DATABASE_URL. "
            "Run 'docker compose up -d postgres' to execute Postgres integration tests."
        )
    return True


@pytest.fixture(autouse=True)
def _skip_postgres_marked_tests_without_db(request):
    """Skip any test marked `postgres` when no pgvector Postgres is reachable, instead of failing."""
    if request.node.get_closest_marker("postgres") and not ensure_postgres_test_env():
        pytest.skip(
            "PostgreSQL 17 with pgvector extension is unreachable at DATABASE_URL/TEST_DATABASE_URL. "
            "Run 'docker compose up -d postgres' to execute Postgres integration tests."
        )


@pytest.fixture(scope="session", autouse=True)
def configure_test_runtime():
    from app.core.limiter import limiter
    from app.storage import reset_storage_backend

    ensure_selector_event_loop()
    limiter.enabled = False
    reset_storage_backend()
    yield
    reset_storage_backend()
