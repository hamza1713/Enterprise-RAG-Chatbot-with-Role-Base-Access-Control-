import os
import shutil
import sqlite3
import sys

print("Starting reset and reindex script...")

# 1. Delete chroma_db directory BEFORE importing rag_module
chroma_db_dir = 'chroma_db'
if os.path.exists(chroma_db_dir):
    print("Deleting chroma_db directory...")
    try:
        shutil.rmtree(chroma_db_dir)
        print("chroma_db deleted.")
    except Exception as e:
        print("Failed to delete chroma_db directory:", e)
else:
    print("chroma_db directory does not exist.")

# 2. Reset embedded column in SQLite database
db_path = 'roles_docs.db'
if os.path.exists(db_path):
    print("Resetting embedded column to 0 in database...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE documents SET embedded = 0")
    conn.commit()
    print("Database reset complete. Total documents:", c.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    conn.close()
else:
    print("roles_docs.db does not exist.")

# 3. Now import and run the indexer
print("Importing run_indexer...")
sys.path.insert(0, '.')
from app.rag_utils.rag_module import run_indexer

print("Running indexer...")
try:
    run_indexer()
    print("Indexer completed successfully.")
except Exception as e:
    import traceback
    print("Indexer failed:")
    traceback.print_exc()
