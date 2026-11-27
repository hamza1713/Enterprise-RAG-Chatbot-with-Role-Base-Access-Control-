"""
app/api/health.py — Health & readiness probes for PostgreSQL/pgvector, Redis, MinIO/S3 & Docling.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
import httpx
from sqlalchemy import text

from app.core.cache import cache_manager
from app.core.config import DOCLING_SERVE_URL, METRICS_AUTH_TOKEN, METRICS_ENABLED, REDIS_URL
from app.core.telemetry import render_prometheus_metrics
from app.db.session import async_session
from app.storage import get_storage_backend

logger = logging.getLogger("FinSight.health")
router = APIRouter(tags=["health"])


@router.get("/")
@router.get("/health")
def health_check():
    """Basic liveness probe."""
    return {"status": "ok", "service": "FinSight API"}


@router.get("/ready")
async def readiness_check():
    """Dependency readiness probe checking Postgres (+pgvector), Redis, Object Storage & Docling."""
    checks: dict[str, str] = {}
    ready = True

    # PostgreSQL + pgvector
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            has_vec = await db.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
        if has_vec:
            checks["postgres"] = "ok"
        else:
            checks["postgres"] = "missing_pgvector_extension"
            ready = False
    except Exception as exc:
        logger.warning(f"[Readiness] Postgres check failed: {exc}")
        checks["postgres"] = "error"
        ready = False

    # Redis (required when REDIS_URL is configured)
    redis_url = os.getenv("REDIS_URL", REDIS_URL).strip()
    if redis_url:
        try:
            if cache_manager.using_redis and cache_manager.redis_client:
                cache_manager.redis_client.ping()
            else:
                import redis

                client = redis.from_url(redis_url, socket_timeout=1.0)
                client.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning(f"[Readiness] Redis check failed: {exc}")
            checks["redis"] = "error"
            ready = False
    else:
        checks["redis"] = "disabled"

    # Object Storage (MinIO / S3 / Local)
    try:
        await get_storage_backend().aensure_bucket()
        checks["storage"] = "ok"
    except Exception as exc:
        logger.warning(f"[Readiness] Object storage check failed: {exc}")
        checks["storage"] = "error"
        ready = False

    # Optional Docling-Serve sidecar (pdfplumber fallback stays healthy)
    docling_url = os.getenv("DOCLING_SERVE_URL", DOCLING_SERVE_URL).strip().rstrip("/")
    if docling_url:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{docling_url}/health")
                checks["docling"] = "ok" if resp.status_code < 400 else "degraded_fallback"
        except Exception:
            checks["docling"] = "degraded_fallback"
    else:
        checks["docling"] = "fallback_pdfplumber"

    # Optional OpenFGA ReBAC sidecar probe (Postgres mirror fallback keeps runtime healthy)
    openfga_url = os.getenv("OPENFGA_API_URL", "").strip().rstrip("/")
    if openfga_url:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{openfga_url}/healthz")
                checks["openfga"] = "ok" if resp.status_code < 400 else "degraded_pg_fallback"
        except Exception:
            checks["openfga"] = "degraded_pg_fallback"
    else:
        checks["openfga"] = "postgres_fallback"

    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "checks": checks},
    )


@router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Internal Prometheus scrape endpoint (gated publicly by Nginx & optional Bearer token)."""
    enabled_env = os.getenv("METRICS_ENABLED")
    is_enabled = (
        enabled_env.strip().lower() == "true" if enabled_env is not None else METRICS_ENABLED
    )
    if not is_enabled:
        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled.")

    expected_token = (os.getenv("METRICS_AUTH_TOKEN") or METRICS_AUTH_TOKEN).strip()
    if expected_token:
        auth_hdr = (request.headers.get("authorization") or "").strip()
        provided = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
        if not provided or not secrets.compare_digest(provided, expected_token):
            raise HTTPException(status_code=401, detail="Invalid or missing metrics bearer token.")

    payload, media_type = render_prometheus_metrics()
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )
