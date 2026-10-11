"""
app/core/limiter.py — Rate limiting configuration using SlowAPI.

Provides:
  - limiter: SlowAPI Limiter instance (configured with Redis or in-memory).
  - rate_limit_exceeded_handler: Standardized JSON 429 response handler.
"""

import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import REDIS_URL, RATE_LIMIT_ENABLED

logger = logging.getLogger("FinSight.limiter")


def get_client_ip(request: Request) -> str:
    """Resolve client IP, prioritizing X-Forwarded-For if behind a proxy / gateway."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# ── Storage backend resolution ────────────────────────────────────────────────
storage_uri = "memory://"
if REDIS_URL:
    try:
        import redis
        # Quick ping to verify Redis is reachable before setting storage URI
        r = redis.from_url(REDIS_URL, socket_timeout=1.0)
        r.ping()
        storage_uri = REDIS_URL
        logger.info(f"[Limiter] Configured with Redis storage at {REDIS_URL}")
    except Exception as exc:
        logger.warning(
            f"[Limiter] Redis unavailable ({exc}). Falling back to in-memory rate limiting."
        )
        storage_uri = "memory://"
else:
    logger.info("[Limiter] Using in-memory rate limiting storage.")

limiter = Limiter(
    key_func=get_client_ip,
    storage_uri=storage_uri,
    enabled=RATE_LIMIT_ENABLED,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a clean, user-friendly HTTP 429 JSON response."""
    client_ip = get_client_ip(request)
    logger.warning(
        f"[RateLimit] Client {client_ip} exceeded rate limit on {request.url.path}: {exc.detail}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}. Please wait before making more requests.",
            "error": "too_many_requests",
        },
    )
