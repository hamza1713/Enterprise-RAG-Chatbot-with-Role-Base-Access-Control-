"""
app/db/session.py — Lazily initialized SQLAlchemy 2.0 sync & async Postgres engines/sessions.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import logging
import os
import threading
from typing import AsyncIterator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_database_url
from app.core.event_loop import ensure_selector_event_loop

logger = logging.getLogger("FinSight.db")

_lock = threading.Lock()
_async_engine: AsyncEngine | None = None
_async_engine_loop: asyncio.AbstractEventLoop | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None
_sync_engine: Engine | None = None
_sync_session_factory: sessionmaker[Session] | None = None


def _current_running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_async_engine() -> AsyncEngine:
    global _async_engine, _async_engine_loop, _async_session_factory
    ensure_selector_event_loop()
    running_loop = _current_running_loop()

    with _lock:
        loop_changed = (
            _async_engine is not None
            and running_loop is not None
            and _async_engine_loop is not None
            and running_loop is not _async_engine_loop
        )
        if _async_engine is None or loop_changed:
            url = get_database_url()
            # Pytest TestClient portals & asyncio.run calls spawn transient loops;
            # NullPool guarantees connections never outlive a closed test event loop.
            if os.getenv("PYTEST_CURRENT_TEST"):
                _async_engine = create_async_engine(url, poolclass=NullPool)
            else:
                _async_engine = create_async_engine(
                    url,
                    pool_pre_ping=True,
                    pool_size=10,
                    max_overflow=20,
                )
            _async_engine_loop = running_loop
            _async_session_factory = async_sessionmaker(
                _async_engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
    assert _async_engine is not None
    return _async_engine


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    get_async_engine()
    assert _async_session_factory is not None
    return _async_session_factory


def get_sync_engine() -> Engine:
    global _sync_engine, _sync_session_factory
    if _sync_engine is None:
        with _lock:
            if _sync_engine is None:
                url = get_database_url()
                _sync_engine = create_engine(
                    url,
                    pool_pre_ping=True,
                    pool_size=10,
                    max_overflow=20,
                )
                _sync_session_factory = sessionmaker(
                    _sync_engine,
                    expire_on_commit=False,
                    class_=Session,
                )
    assert _sync_engine is not None
    return _sync_engine


def get_sync_session_factory() -> sessionmaker[Session]:
    get_sync_engine()
    assert _sync_session_factory is not None
    return _sync_session_factory


@asynccontextmanager
async def async_session() -> AsyncIterator[AsyncSession]:
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


@contextmanager
def sync_session() -> Iterator[Session]:
    factory = get_sync_session_factory()
    with factory() as session:
        yield session


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession."""
    factory = get_async_session_factory()
    async with factory() as session:
        yield session


async def close_db_engines() -> None:
    """Dispose both async and sync engines cleanly on shutdown or worker exit."""
    global _async_engine, _async_engine_loop, _async_session_factory, _sync_engine, _sync_session_factory
    with _lock:
        async_eng = _async_engine
        sync_eng = _sync_engine
        _async_engine = None
        _async_engine_loop = None
        _async_session_factory = None
        _sync_engine = None
        _sync_session_factory = None
    if async_eng is not None:
        await async_eng.dispose()
    if sync_eng is not None:
        sync_eng.dispose()


def reset_db_engines() -> None:
    """Synchronously reset cached engines (intended for test environment changes)."""
    global _async_engine, _async_engine_loop, _async_session_factory, _sync_engine, _sync_session_factory
    with _lock:
        sync_eng = _sync_engine
        _async_engine = None
        _async_engine_loop = None
        _async_session_factory = None
        _sync_engine = None
        _sync_session_factory = None
    if sync_eng is not None:
        sync_eng.dispose()
