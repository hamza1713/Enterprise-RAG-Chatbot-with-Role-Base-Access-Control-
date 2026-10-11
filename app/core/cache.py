"""
app/core/cache.py — Multi-tier query & response cache with Redis and in-memory fallback.

Provides:
  - CacheManager: Unified interface for caching JSON responses.
  - Role-scoped cache key generator: prevents cross-role data leaks.
  - Automatic fallback to in-memory TTL store if Redis is unavailable.
"""

import hashlib
import json
import logging
import re
import time
from typing import Any

from app.core.config import REDIS_URL, CACHE_TTL_SECONDS

logger = logging.getLogger("FinSight.cache")


class InMemoryTTLCache:
    """Thread-safe in-memory cache with TTL and maximum size eviction."""

    def __init__(self, max_size: int = 1000):
        self._store: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        now = time.time()
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at and now > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        now = time.time()
        # Evict expired entries if approaching max size
        if len(self._store) >= self._max_size:
            self._cleanup_expired(now)
            if len(self._store) >= self._max_size:
                # Remove oldest entry
                oldest_key = next(iter(self._store))
                self._store.pop(oldest_key, None)

        expires_at = now + ttl if ttl > 0 else 0
        self._store[key] = (value, expires_at)
        return True

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def delete_prefix(self, prefix: str) -> int:
        keys_to_delete = [k for k in list(self._store.keys()) if k.startswith(prefix)]
        for k in keys_to_delete:
            self._store.pop(k, None)
        return len(keys_to_delete)

    def clear(self) -> None:
        self._store.clear()

    def _cleanup_expired(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._store.items() if exp and now > exp]
        for k in expired:
            self._store.pop(k, None)


class CacheManager:
    """
    Production Cache Manager:
    Connects to Redis if available, else falls back to InMemoryTTLCache.
    """

    def __init__(self, redis_url: str = REDIS_URL, default_ttl: int = CACHE_TTL_SECONDS):
        self.default_ttl = default_ttl
        self.redis_client = None
        self.memory_cache = InMemoryTTLCache(max_size=2000)
        self.using_redis = False

        if redis_url:
            try:
                import redis
                r = redis.from_url(redis_url, socket_timeout=1.5, decode_responses=True)
                r.ping()
                self.redis_client = r
                self.using_redis = True
                logger.info(f"[CacheManager] Connected to Redis at {redis_url}")
            except Exception as exc:
                logger.warning(
                    f"[CacheManager] Redis connection failed ({exc}). Using in-memory TTL cache."
                )
        else:
            logger.info("[CacheManager] No REDIS_URL provided. Using in-memory TTL cache.")

    @staticmethod
    def normalize_question(question: str) -> str:
        """Strip extra whitespaces, normalize punctuation and casing."""
        q = question.strip().lower()
        q = re.sub(r"\s+", " ", q)
        q = re.sub(r"[?!.,;]+$", "", q).strip()
        return q

    def build_cache_key(self, role: str, question: str) -> str:
        """
        Generate a secure, role-scoped cache key.
        Security Rule: Role MUST be prepended to guarantee zero cross-role data leaks.
        """
        clean_role = (role or "general").strip().lower()
        clean_q = self.normalize_question(question)
        digest = hashlib.sha256(clean_q.encode("utf-8")).hexdigest()[:32]
        return f"finsight:cache:{clean_role}:{digest}"

    def get(self, key: str) -> dict | None:
        if self.using_redis and self.redis_client:
            try:
                raw = self.redis_client.get(key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as exc:
                logger.warning(f"[CacheManager] Redis GET error ({exc}). Falling back to memory.")

        return self.memory_cache.get(key)

    def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
        ttl = ttl if ttl is not None else self.default_ttl
        if self.using_redis and self.redis_client:
            try:
                raw = json.dumps(value)
                self.redis_client.set(key, raw, ex=ttl)
                return True
            except Exception as exc:
                logger.warning(f"[CacheManager] Redis SET error ({exc}). Falling back to memory.")

        return self.memory_cache.set(key, value, ttl=ttl)

    def delete_prefix(self, prefix: str) -> int:
        """Invalidate all keys matching prefix (e.g. finsight:cache:hr:)."""
        deleted_count = self.memory_cache.delete_prefix(prefix)
        if self.using_redis and self.redis_client:
            try:
                keys = self.redis_client.keys(f"{prefix}*")
                if keys:
                    deleted_count += self.redis_client.delete(*keys)
            except Exception as exc:
                logger.warning(f"[CacheManager] Redis DELETE_PREFIX error: {exc}")
        return deleted_count

    def clear(self) -> None:
        self.memory_cache.clear()
        if self.using_redis and self.redis_client:
            try:
                keys = self.redis_client.keys("finsight:cache:*")
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as exc:
                logger.warning(f"[CacheManager] Redis CLEAR error: {exc}")


# Global singleton instance
cache_manager = CacheManager()
