"""
app/main.py — FastAPI application factory.

This file is now a thin orchestrator:
  1. Configures logging.
  2. Runs startup lifecycle (DB init, user seed, preload data).
  3. Registers all domain routers.
  4. Adds CORS middleware.

All business logic has been moved to:
  - app/core/   — config, database, security, users
  - app/api/    — auth, chat, documents, admin, health, evaluate routers
  - app/rag/    — RAG engine
  - app/rag_evaluator/ — RAGAS quality + RBAC security evaluation
"""

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import CORS_ORIGINS
from app.core.database import init_sqlite_schema, init_duckdb_schema, heal_stale_filepaths, reconcile_duckdb_from_sqlite, preload_default_data
from app.core.users import seed_default_users

from app.api.auth      import router as auth_router
from app.api.chat      import router as chat_router
from app.api.documents import router as documents_router
from app.api.admin     import router as admin_router
from app.api.health    import router as health_router
from app.api.evaluate  import router as evaluate_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("FinSight")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    logger.info("[Startup] Initialising FinSight…")

    # Schema creation is idempotent — safe to call on every boot
    init_sqlite_schema()
    init_duckdb_schema()

    # Seed default users & roles
    seed_default_users()

    # Auto-correct any DB filepaths that still point to an old project directory
    heal_stale_filepaths()

    # Reconcile DuckDB tables from SQLite (synchronous, fast)
    reconcile_duckdb_from_sqlite()

    # Preload documents from resources/data/ in the background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, preload_default_data)

    logger.info("[Startup] FinSight is ready.")
    yield
    logger.info("[Shutdown] FinSight shutting down.")


# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="FinSight API",
    description="Role-Based AI Workspace — document Q&A, SQL analytics, and admin controls.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(admin_router)
app.include_router(evaluate_router)