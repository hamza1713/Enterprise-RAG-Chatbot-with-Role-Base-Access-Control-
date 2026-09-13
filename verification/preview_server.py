"""Run an isolated local UI check with synthetic documents and offline AI keys.

Usage: python -m verification.preview_server
This does not load the developer's database or submit documents to an AI provider.
"""
import os
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix='finsight-preview-'))
os.environ.update({
    'APP_ENV': 'development', 'PRELOAD_SAMPLE_DATA': 'false',
    'DB_NAME': str(root / 'roles.db'), 'DUCKDB_NAME': str(root / 'tables.duckdb'),
    'UPLOAD_DIR': str(root / 'uploads'), 'CHROMA_DIR': str(root / 'chroma'),
    'EVAL_OUTPUT_DIR': str(root / 'evaluation'),
    'JWT_SECRET': 'local-preview-only-signing-key-at-least-32-chars',
    'GOOGLE_API_KEY': 'offline-preview', 'COHERE_API_KEY': '', 'LANGCHAIN_API_KEY': '',
})
from app.core.database import init_sqlite_schema, init_duckdb_schema, get_db_conn
from app.core.users import seed_default_users
init_sqlite_schema()
init_duckdb_schema()
seed_default_users()
document = root / 'uploads' / 'workspace-guide.md'
document.write_text('# Preview workspace\n\nThis is a synthetic document for interface verification.\n\n## Working with knowledge\n\n- Browse documents in the library.\n- Ask questions in the AI assistant.\n- Administrators can upload documents and manage access.\n', encoding='utf-8')
conn = get_db_conn()
conn.execute('INSERT INTO documents (filename, filepath, role, embedded) VALUES (?,?,?,?)',
             (document.name, str(document), 'General', 1))
conn.commit()
conn.close()

from app.main import app
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
