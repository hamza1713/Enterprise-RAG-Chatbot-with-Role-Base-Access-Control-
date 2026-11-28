"""
app/storage/base.py — Abstract protocol and safety normalization for Object Storage.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import tempfile
from typing import AsyncIterator, Iterator


def normalize_object_key(key: str) -> str:
    """Validate and canonicalize an object storage key, rejecting path traversal."""
    clean = (key or "").replace("\\", "/").strip().lstrip("/")
    if not clean or "\x00" in clean or ":" in clean.split("/")[0]:
        raise ValueError(f"Invalid object key: {key!r}")
    parts = [part for part in clean.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Invalid object key segments: {key!r}")
    return "/".join(parts)


class ObjectStorageBackend(ABC):
    """Protocol implemented by S3/MinIO and local temporary-vault object storage backends."""

    @abstractmethod
    def ensure_bucket(self) -> None:
        """Ensure the configured bucket/root directory exists."""

    @abstractmethod
    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store raw bytes under canonical key and return the canonical key."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Retrieve raw bytes for key; raise FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete key if present (idempotent)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if key exists in storage."""

    @contextmanager
    def open_local_temp(self, key: str, suffix: str = "") -> Iterator[Path]:
        """Materialize key to a temporary local file cleaned up on exit."""
        raw = self.get_bytes(key)
        ext = suffix or Path(normalize_object_key(key)).suffix
        with tempfile.TemporaryDirectory(prefix="finsight-obj-") as tmpdir:
            tmp_path = Path(tmpdir) / f"payload{ext}"
            tmp_path.write_bytes(raw)
            yield tmp_path

    async def aensure_bucket(self) -> None:
        await asyncio.to_thread(self.ensure_bucket)

    async def aput_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return await asyncio.to_thread(self.put_bytes, key, data, content_type)

    async def aget_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.get_bytes, key)

    async def adelete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    async def aexists(self, key: str) -> bool:
        return await asyncio.to_thread(self.exists, key)

    @asynccontextmanager
    async def aopen_local_temp(self, key: str, suffix: str = "") -> AsyncIterator[Path]:
        """Async context manager yielding a local temp file cleaned up on exit."""
        raw = await self.aget_bytes(key)
        ext = suffix or Path(normalize_object_key(key)).suffix
        with tempfile.TemporaryDirectory(prefix="finsight-obj-") as tmpdir:
            tmp_path = Path(tmpdir) / f"payload{ext}"
            await asyncio.to_thread(tmp_path.write_bytes, raw)
            yield tmp_path
