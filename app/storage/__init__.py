"""
app/storage/__init__.py — Lazily constructed singleton factory for ObjectStorageBackend.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from app.core.config import UPLOAD_DIR
from app.storage.base import ObjectStorageBackend, normalize_object_key
from app.storage.local import LocalObjectStorage
from app.storage.s3 import S3ObjectStorage

__all__ = [
    "ObjectStorageBackend",
    "LocalObjectStorage",
    "S3ObjectStorage",
    "get_storage_backend",
    "reset_storage_backend",
    "normalize_object_key",
]

_lock = threading.Lock()
_backend: ObjectStorageBackend | None = None


def get_storage_backend() -> ObjectStorageBackend:
    """Return the configured ObjectStorageBackend (S3/MinIO or LocalObjectStorage)."""
    global _backend
    if _backend is None:
        with _lock:
            if _backend is None:
                mode = os.getenv("STORAGE_BACKEND", "s3").strip().lower()
                if mode == "local":
                    root = Path(os.getenv("UPLOAD_DIR", str(UPLOAD_DIR)))
                    _backend = LocalObjectStorage(root_dir=root)
                else:
                    _backend = S3ObjectStorage(
                        bucket=os.getenv("S3_BUCKET", "finsight-documents").strip(),
                        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000").strip() or None,
                        access_key=os.getenv("S3_ACCESS_KEY", "").strip() or None,
                        secret_key=os.getenv("S3_SECRET_KEY", "").strip() or None,
                        region=os.getenv("S3_REGION", "us-east-1").strip() or "us-east-1",
                    )
    return _backend


def reset_storage_backend() -> None:
    """Clear the cached storage backend singleton (primarily for tests)."""
    global _backend
    with _lock:
        _backend = None
