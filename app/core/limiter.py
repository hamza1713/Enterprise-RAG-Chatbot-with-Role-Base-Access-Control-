"""
app/core/limiter.py — Rate limiting configuration using SlowAPI.

Provides:
  - limiter: SlowAPI Limiter instance (configured with Redis or in-memory).
  - rate_limit_exceeded_handler: Standardized JSON 429 response handler.
"""

import ipaddress
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import REDIS_URL, RATE_LIMIT_ENABLED, TRUSTED_PROXY_IPS

logger = logging.getLogger("FinSight.limiter")


def _parse_trusted_networks(entries: list[str]) -> tuple[ipaddress._BaseNetwork, ...]:
    nets: list[ipaddress._BaseNetwork] = []
    for entry in entries:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"Ignoring invalid TRUSTED_PROXY_IPS entry: {entry!r}")
    return tuple(nets)


_TRUSTED_PROXY_NETS = _parse_trusted_networks(TRUSTED_PROXY_IPS)


def _is_trusted_proxy(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXY_NETS)


def _extract_valid_ip(raw_value: str) -> str | None:
    candidate = raw_value.strip()
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    """Resolve client IP, trusting forwarded headers only from configured proxy CIDRs."""
    remote_ip = get_remote_address(request) or "127.0.0.1"
    if not _is_trusted_proxy(remote_ip):
        return remote_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        hops = [ip for part in forwarded.split(",") if (ip := _extract_valid_ip(part))]
        for hop in reversed(hops):
            if not _is_trusted_proxy(hop):
                return hop
        if hops:
            return hops[0]

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        parsed_real = _extract_valid_ip(real_ip)
        if parsed_real:
            return parsed_real

    return remote_ip


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
