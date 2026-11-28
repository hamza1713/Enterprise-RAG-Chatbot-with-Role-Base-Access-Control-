"""Run an isolated local UI check with synthetic documents and offline AI keys.

Usage: python -m verification.preview_server
Requires a running PostgreSQL instance (`alembic upgrade head` applied).
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import uuid

root = Path(tempfile.mkdtemp(prefix="finsight-preview-"))
os.environ.update(
    {
        "APP_ENV": "development",
        "PRELOAD_SAMPLE_DATA": "false",
        "STORAGE_BACKEND": "local",
        "UPLOAD_DIR": str(root / "uploads"),
        "EVAL_OUTPUT_DIR": str(root / "evaluation"),
        "JWT_SECRET": "local-preview-only-signing-key-at-least-32-chars",
        "GOOGLE_API_KEY": "offline-preview",
        "COHERE_API_KEY": "",
        "LANGCHAIN_API_KEY": "",
    }
)

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.core.users import seed_default_users
from app.db.models import DocumentRecord
from app.db.session import sync_session
from app.main import app
from app.storage import get_storage_backend

alembic_cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
command.upgrade(alembic_cfg, "head")
seed_default_users()

storage = get_storage_backend()
storage.ensure_bucket()
guide_text = (
    "# Preview workspace\n\n"
    "This is a synthetic document for interface verification.\n\n"
    "## Working with knowledge\n\n"
    "- Browse documents in the library.\n"
    "- Ask questions in the AI assistant.\n"
    "- Administrators can upload documents and manage access.\n"
).encode("utf-8")

object_key = storage.put_bytes(
    f"documents/General/{uuid.uuid4().hex}_workspace-guide.md",
    guide_text,
    content_type="text/markdown",
)

with sync_session() as db:
    existing = db.scalar(
        select(DocumentRecord).where(
            func.lower(DocumentRecord.filename) == "workspace-guide.md",
            func.lower(DocumentRecord.role) == "general",
        )
    )
    if existing is None:
        db.add(
            DocumentRecord(
                filename="workspace-guide.md",
                role="General",
                object_key=object_key,
                content_type="text/markdown",
                size_bytes=len(guide_text),
                parser_used="markdown",
                embedded=1,
            )
        )
        db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
