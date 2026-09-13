"""Keep every test store separate from developer documents and indexes."""
import os
import tempfile
from pathlib import Path
import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix='finsight-tests-'))
os.environ.update({
    'APP_ENV': 'development',
    'DB_NAME': str(TEST_ROOT / 'roles.db'),
    'DUCKDB_NAME': str(TEST_ROOT / 'tables.duckdb'),
    'UPLOAD_DIR': str(TEST_ROOT / 'uploads'),
    'CHROMA_DIR': str(TEST_ROOT / 'chroma'),
    'EVAL_OUTPUT_DIR': str(TEST_ROOT / 'evaluation'),
    'JWT_SECRET': 'offline-test-signing-secret-at-least-32-characters',
    'GOOGLE_API_KEY': 'offline-test-key',
    'COHERE_API_KEY': '',
    'LANGCHAIN_API_KEY': '',
})

@pytest.fixture(scope='session', autouse=True)
def init_test_db():
    from app.core.database import init_sqlite_schema, init_duckdb_schema
    from app.core.users import seed_default_users
    init_sqlite_schema()
    init_duckdb_schema()
    seed_default_users()
