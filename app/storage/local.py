"""
app/storage/local.py — Local filesystem ObjectStorageBackend for offline dev and tests.
"""

from __future__ import annotations

from pathlib import Path

from app.storage.base import ObjectStorageBackend, normalize_object_key


class LocalObjectStorage(ObjectStorageBackend):
    """Stores objects cleanly inside a sandboxed root directory."""

    def __init__(self, root_dir: Path | str):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        canonical = normalize_object_key(key)
        target = (self.root_dir / canonical).resolve()
        if not target.is_relative_to(self.root_dir):
            raise ValueError(f"Object key escapes storage root: {key!r}")
        return target

    def ensure_bucket(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        canonical = normalize_object_key(key)
        target = self._resolve(canonical)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return canonical

    def get_bytes(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise FileNotFoundError(f"Object not found: {key}")
        return target.read_bytes()

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.is_file():
            target.unlink()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()
