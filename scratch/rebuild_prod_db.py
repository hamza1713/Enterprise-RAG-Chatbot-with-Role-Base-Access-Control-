import os
import sqlite3
import sys
from pathlib import Path

# Add root directory to Python path
sys.path.insert(0, '.')

# Ensure we are working on the production database
os.environ["DB_NAME"] = "roles_docs.db"

print("Starting production database rebuild...")

# 1. Delete the existing production SQLite database to start fresh
db_path = 'roles_docs.db'
if os.path.exists(db_path):
    print("Deleting existing roles_docs.db...")
    try:
        os.remove(db_path)
        print("Deleted roles_docs.db successfully.")
    except Exception as e:
        print("Failed to delete roles_docs.db:", e)
else:
    print("roles_docs.db does not exist. A new one will be created.")

# Also delete duckdb file to rebuild tables
duckdb_path = Path("static/data/structured_queries.duckdb")
if duckdb_path.exists():
    print("Deleting existing DuckDB structured queries database...")
    try:
        os.remove(duckdb_path)
        print("Deleted structured_queries.duckdb successfully.")
    except Exception as e:
        print("Failed to delete DuckDB database:", e)

# 2. Import main to trigger DB initialization and preloading
print("Importing app.main and running preload...")
from app.main import preload_default_data, create_default_user

# Re-create default user and roles
create_default_user()

# Run preload of default data
preload_default_data()

# 3. Check what was preloaded
conn = sqlite3.connect("roles_docs.db")
c = conn.cursor()
c.execute("SELECT id, filename, role, embedded FROM documents")
docs = c.fetchall()
print(f"Preloaded {len(docs)} documents in SQLite:")
for d in docs:
    print(f" - ID: {d[0]}, Filename: {d[1]}, Role: {d[2]}, Embedded: {d[3]}")
conn.close()

print("Rebuild completed successfully. Now run indexer to embed.")
