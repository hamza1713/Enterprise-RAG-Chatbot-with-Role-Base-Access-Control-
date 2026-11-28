"""
app/workers/broker.py — Taskiq broker & lifecycle hooks (Redis + InMemory test fallback).
"""

from __future__ import annotations

import logging
import os

from taskiq import InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from app.core.event_loop import ensure_selector_event_loop
from app.core.logging_config import configure_logging
from app.db.session import close_db_engines
from app.storage import get_storage_backend

ensure_selector_event_loop()
configure_logging()
logger = logging.getLogger("FinSight.workers.broker")


def _build_broker():
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        result_backend = RedisAsyncResultBackend(redis_url=redis_url)
        return ListQueueBroker(url=redis_url).with_result_backend(result_backend)
    logger.info("[Taskiq] REDIS_URL unset — using InMemoryBroker (offline/test mode).")
    return InMemoryBroker()


broker = _build_broker()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _on_worker_startup(_state: TaskiqState) -> None:
    ensure_selector_event_loop()
    try:
        await get_storage_backend().aensure_bucket()
    except Exception as exc:
        logger.warning(f"[Taskiq] Bucket check on worker startup skipped/failed: {exc}")
    logger.info("[Taskiq] Worker initialized and ready.")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _on_worker_shutdown(_state: TaskiqState) -> None:
    await close_db_engines()
    logger.info("[Taskiq] Worker shut down cleanly.")
