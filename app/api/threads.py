"""
app/api/threads.py — Persistent user-scoped chat threads & message history CRUD.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_checkpointer
from app.api.auth import get_current_user
from app.db.models import ChatMessageRecord, ChatThread
from app.db.session import get_db

logger = logging.getLogger("FinSight.threads")
router = APIRouter(tags=["threads"])


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="New Conversation", max_length=160)


class ThreadPatchRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    archived: bool | None = None


def _serialize_thread(thread: ChatThread) -> dict:
    return {
        "id": thread.id,
        "username": thread.username,
        "title": thread.title,
        "archived": bool(thread.archived),
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "updated_at": thread.updated_at.isoformat() if thread.updated_at else None,
    }


def _serialize_message(msg: ChatMessageRecord) -> dict:
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "role": msg.role,
        "content": msg.content,
        "mode": msg.mode,
        "sql": msg.sql_query,
        "chart_spec": msg.chart_spec,
        "citations": list(msg.citations_json or []),
        "agent_steps": list(msg.agent_steps_json or []),
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def _get_owned_thread(
    db: AsyncSession, thread_id: str, username: str
) -> ChatThread:
    try:
        uuid.UUID(str(thread_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Conversation thread not found.") from exc

    thread = await db.scalar(select(ChatThread).where(ChatThread.id == thread_id))
    if thread is None or thread.username.lower() != username.lower():
        raise HTTPException(status_code=404, detail="Conversation thread not found.")
    return thread


@router.get("/threads")
async def list_threads(
    include_archived: bool = False,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ChatThread).where(
        func.lower(ChatThread.username) == user["username"].lower()
    )
    if not include_archived:
        stmt = stmt.where(ChatThread.archived.is_(False))
    stmt = stmt.order_by(ChatThread.updated_at.desc(), ChatThread.created_at.desc())
    rows = list(await db.scalars(stmt))
    return {"threads": [_serialize_thread(t) for t in rows]}


@router.post("/threads")
async def create_thread(
    body: ThreadCreateRequest | None = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    title = ((body.title if body else "") or "New Conversation").strip() or "New Conversation"
    thread = ChatThread(
        id=str(uuid.uuid4()),
        username=user["username"],
        title=title[:160],
        archived=False,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return _serialize_thread(thread)


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _get_owned_thread(db, thread_id, user["username"])
    messages = list(
        await db.scalars(
            select(ChatMessageRecord)
            .where(ChatMessageRecord.thread_id == thread.id)
            .order_by(ChatMessageRecord.id.asc())
        )
    )
    return {
        "thread": _serialize_thread(thread),
        "messages": [_serialize_message(m) for m in messages],
    }


@router.patch("/threads/{thread_id}")
async def update_thread(
    thread_id: str,
    body: ThreadPatchRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _get_owned_thread(db, thread_id, user["username"])
    if body.title is not None:
        clean_title = body.title.strip()
        if not clean_title:
            raise HTTPException(status_code=400, detail="Thread title cannot be empty.")
        thread.title = clean_title[:160]
    if body.archived is not None:
        thread.archived = bool(body.archived)
    thread.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(thread)
    return _serialize_thread(thread)


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    thread = await _get_owned_thread(db, thread_id, user["username"])
    await db.delete(thread)
    await db.commit()

    saver = get_checkpointer()
    if hasattr(saver, "adelete_thread"):
        try:
            await saver.adelete_thread(thread_id)
        except Exception as exc:
            logger.debug(f"[Threads] Checkpoint cleanup skipped for {thread_id}: {exc}")

    return {"message": "Conversation thread deleted.", "thread_id": thread_id}
