"""
app/main.py — Stateless FastAPI multi-worker application factory.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.agents.graph import init_agent_runtime, shutdown_agent_runtime
from app.api.admin import router as admin_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.evaluate import router as evaluate_router
from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.semantic import router as semantic_router
from app.api.threads import router as threads_router
from app.authz.openfga import get_rebac_service
from app.core.config import APP_ENV, COOKIE_SECURE, CORS_ORIGINS
from app.core.database import init_postgres_seed, preload_default_data
from app.core.event_loop import ensure_selector_event_loop
from app.core.limiter import limiter, rate_limit_exceeded_handler
from app.core.logging_config import configure_logging
from app.core.security import SESSION_SECRET
from app.core.telemetry import ObservabilityMiddleware, init_telemetry
from app.db.session import close_db_engines
from app.workers.broker import broker
from app.workers.tasks import index_document_task

ensure_selector_event_loop()
configure_logging()
logger = logging.getLogger("FinSight")


@asynccontextmanager
async def lifespan(_app_instance: FastAPI):
    logger.info("[Startup] Initialising FinSight…")
    ensure_selector_event_loop()

    broker_started = False
    if not broker.is_worker_process:
        await broker.startup()
        broker_started = True

    await init_agent_runtime()
    try:
        await asyncio.to_thread(init_postgres_seed)
        await get_rebac_service().async_all_to_openfga()
        preload_default = "false" if APP_ENV == "production" else "true"
        if os.getenv("PRELOAD_SAMPLE_DATA", preload_default).lower() == "true":
            created_jobs = await asyncio.to_thread(preload_default_data)
            for job_id, doc_id in created_jobs:
                await index_document_task.kiq(job_id, doc_id)
    except Exception as exc:
        logger.warning(f"[Startup] Seed/preload warning: {exc}")

    logger.info("[Startup] FinSight is ready.")
    try:
        yield
    finally:
        logger.info("[Shutdown] FinSight shutting down.")
        if broker_started:
            await broker.shutdown()
        await shutdown_agent_runtime()
        await close_db_engines()


app = FastAPI(
    title="FinSight API",
    description="Agentic Enterprise AI Workspace — OpenFGA ReBAC, LangGraph 1.2, Semantic DuckDB SQL & RAGAS.",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="finsight_oidc_tx",
    same_site="lax",
    https_only=COOKIE_SECURE,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ObservabilityMiddleware)
init_telemetry(app)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(threads_router)
app.include_router(documents_router)
app.include_router(semantic_router)
app.include_router(admin_router)
app.include_router(audit_router)
app.include_router(jobs_router)
app.include_router(evaluate_router)
