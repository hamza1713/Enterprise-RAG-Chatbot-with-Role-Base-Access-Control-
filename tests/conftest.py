import pytest
import os
from pathlib import Path

import os
os.environ["DB_NAME"] = "test_roles_docs.db"
os.environ["DUCKDB_NAME"] = "test_structured_queries.duckdb"

# Clean databases at startup before any imports hold file locks
db_file = Path("test_roles_docs.db")
if db_file.exists():
    try:
        db_file.unlink()
        print("[OK] Deleted test_roles_docs.db for clean test run.")
    except Exception as e:
        print("Failed to delete test_roles_docs.db:", e)
        
duckdb_file = Path("static/data/test_structured_queries.duckdb")
if duckdb_file.exists():
    try:
        duckdb_file.unlink()
        print("[OK] Deleted test_structured_queries.duckdb for clean test run.")
    except Exception as e:
        print("Failed to delete DuckDB file:", e)

@pytest.fixture(scope="session", autouse=True)
def init_test_db():
    from app.core.database import init_sqlite_schema, init_duckdb_schema
    from app.core.users import seed_default_users
    init_sqlite_schema()
    init_duckdb_schema()
    seed_default_users()

@pytest.fixture(scope="function")
def context(browser):
    return browser.new_context(record_video_dir="videos/")

@pytest.fixture(scope="function")
def page(context):
    return context.new_page()