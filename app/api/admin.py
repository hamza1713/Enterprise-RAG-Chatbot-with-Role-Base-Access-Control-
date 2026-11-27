"""
app/api/admin.py — User, Role & Knowledge-Base Indexing administration endpoints (C-Level only).
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.authz.openfga import get_rebac_service
from app.core.cache import cache_manager
from app.core.security import hash_password
from app.core.users import _SYSTEM_ROLES
from app.db.models import DocumentRecord, Role, User
from app.db.session import get_db
from app.workers.tasks import enqueue_full_reindex_job, enqueue_retry_failed_job

logger = logging.getLogger("FinSight.admin")
router = APIRouter(tags=["admin"])

_CLEVEL = "c-level"


class UserPatchRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    password: str


def _require_clevel(user: dict = Depends(get_current_user)) -> dict:
    if user["role"].lower() != _CLEVEL:
        raise HTTPException(
            status_code=403,
            detail="Only C-Level users can perform this action.",
        )
    return user


def _validate_password_policy(password: str) -> None:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=400,
            detail="Passwords must have at least 12 characters and at most 72 UTF-8 bytes.",
        )


def _serialize_user(user_obj: User) -> dict:
    return {
        "id": user_obj.id,
        "username": user_obj.username,
        "role": user_obj.role_name,
        "is_active": bool(user_obj.is_active),
        "created_at": user_obj.created_at.isoformat() if user_obj.created_at else None,
        "updated_at": user_obj.updated_at.isoformat() if user_obj.updated_at else None,
    }


async def _count_active_clevels(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.role_name) == _CLEVEL, User.is_active.is_(True))
        )
        or 0
    )


# ── Roles ─────────────────────────────────────────────────────────────────────


@router.get("/roles")
async def get_roles(
    _user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = list(await db.scalars(select(Role).order_by(Role.id.asc())))
    return {
        "roles": [r.role_name for r in rows],
        "role_details": [
            {
                "id": r.id,
                "role_name": r.role_name,
                "is_system": bool(r.is_system or r.role_name.lower() in _SYSTEM_ROLES),
            }
            for r in rows
        ],
    }


@router.post("/create-role")
async def create_role(
    role_name: str = Form(...),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    clean_name = role_name.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,39}", clean_name):
        raise HTTPException(
            status_code=400,
            detail="Use 2–40 letters, numbers, underscores, or hyphens for a role, starting with a letter.",
        )
    existing = await db.scalar(
        select(Role).where(func.lower(Role.role_name) == clean_name.lower())
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Role already exists")

    db.add(Role(role_name=clean_name, is_system=clean_name.lower() in _SYSTEM_ROLES))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Role already exists") from exc

    return {"message": f"Role '{clean_name}' created."}


@router.delete("/roles/{role_name}")
async def delete_role(
    role_name: str,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    target = await db.scalar(
        select(Role).where(func.lower(Role.role_name) == role_name.strip().lower())
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    if target.is_system or target.role_name.lower() in _SYSTEM_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"System role '{target.role_name}' cannot be deleted.",
        )

    assigned_users = int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.role_name) == target.role_name.lower())
        )
        or 0
    )
    assigned_docs = int(
        await db.scalar(
            select(func.count())
            .select_from(DocumentRecord)
            .where(func.lower(DocumentRecord.role) == target.role_name.lower())
        )
        or 0
    )
    if assigned_users > 0 or assigned_docs > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete role '{target.role_name}': {assigned_users} user(s) "
                f"and {assigned_docs} document(s) remain assigned to it."
            ),
        )

    await db.delete(target)
    await db.commit()
    return {"message": f"Role '{target.role_name}' deleted."}


# ── Users CRUD ────────────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    rows = list(await db.scalars(select(User).order_by(User.id.asc())))
    return {"users": [_serialize_user(u) for u in rows]}


@router.post("/create-user")
async def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    current_admin: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    clean_username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", clean_username):
        raise HTTPException(
            status_code=400,
            detail="Usernames must be 3–64 letters, numbers, periods, underscores, or hyphens.",
        )
    _validate_password_policy(password)

    role_row = await db.scalar(
        select(Role).where(func.lower(Role.role_name) == role.strip().lower())
    )
    if role_row is None:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing_user = await db.scalar(
        select(User).where(func.lower(User.username) == clean_username.lower())
    )
    if existing_user is not None:
        raise HTTPException(status_code=400, detail="User already exists")

    db.add(
        User(
            username=clean_username,
            password_hash=hash_password(password),
            role_name=role_row.role_name,
            is_active=True,
            token_version=1,
        )
    )
    try:
        await db.flush()
        await get_rebac_service().async_user_roles(
            db,
            clean_username,
            role_row.role_name,
            is_active=True,
            created_by=current_admin["username"],
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User already exists") from exc

    return {"message": f"User '{clean_username}' created with role '{role_row.role_name}'."}


@router.patch("/users/{username}")
async def update_user(
    username: str,
    body: UserPatchRequest,
    current_user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    if body.role is None and body.is_active is None:
        raise HTTPException(status_code=400, detail="Specify 'role' and/or 'is_active' to update.")

    target = await db.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    is_self = target.username.lower() == current_user["username"].lower()
    if is_self:
        if body.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
        if body.role is not None and body.role.strip().lower() != _CLEVEL:
            raise HTTPException(status_code=400, detail="You cannot demote your own C-Level role.")

    new_role_name = target.role_name
    if body.role is not None:
        role_row = await db.scalar(
            select(Role).where(func.lower(Role.role_name) == body.role.strip().lower())
        )
        if role_row is None:
            raise HTTPException(status_code=400, detail="Invalid role.")
        new_role_name = role_row.role_name

    new_active = target.is_active if body.is_active is None else bool(body.is_active)

    currently_active_clevel = target.role_name.lower() == _CLEVEL and bool(target.is_active)
    remains_active_clevel = new_role_name.lower() == _CLEVEL and new_active
    if currently_active_clevel and not remains_active_clevel:
        if await _count_active_clevels(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote or deactivate the last active C-Level administrator.",
            )

    old_role_name = target.role_name
    target.role_name = new_role_name
    target.is_active = new_active
    target.token_version = int(target.token_version or 1) + 1
    await get_rebac_service().async_user_roles(
        db,
        target.username,
        new_role_name,
        is_active=new_active,
        previous_role=old_role_name,
        created_by=current_user["username"],
    )
    await db.commit()
    await db.refresh(target)
    return _serialize_user(target)


@router.post("/users/{username}/reset-password")
async def reset_user_password(
    username: str,
    body: ResetPasswordRequest,
    _current_user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    _validate_password_policy(body.password)

    target = await db.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    target.password_hash = hash_password(body.password)
    target.token_version = int(target.token_version or 1) + 1
    await db.commit()
    return {"message": f"Password updated for '{target.username}' and existing sessions revoked."}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    current_user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    target = await db.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if target.username.lower() == current_user["username"].lower():
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    if target.role_name.lower() == _CLEVEL and bool(target.is_active):
        if await _count_active_clevels(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the last active C-Level administrator.",
            )

    deleted_name = target.username
    deleted_role = target.role_name
    await get_rebac_service().async_user_roles(
        db,
        deleted_name,
        deleted_role,
        is_active=False,
        previous_role=deleted_role,
        created_by=current_user["username"],
    )
    await db.delete(target)
    await db.commit()
    return {"message": f"User '{deleted_name}' deleted."}


# ── Indexing status ───────────────────────────────────────────────────────────


@router.get("/indexing-status")
async def get_indexing_status(
    filename: str,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """Per-file status — used by the upload progress bar."""
    doc = await db.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.filename == filename)
        .order_by(DocumentRecord.id.desc())
        .limit(1)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "embedded": doc.embedded,
        "total_chunks": doc.total_chunks,
        "embedded_chunks": doc.embedded_chunks,
        "parser_used": doc.parser_used,
        "last_error": doc.last_error,
    }


@router.get("/indexing-status-bulk")
async def get_indexing_status_bulk(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    rows = list(
        await db.scalars(
            select(DocumentRecord).order_by(DocumentRecord.embedded.asc(), DocumentRecord.id.asc())
        )
    )

    total = done = failed = pending = 0
    docs: list[dict] = []
    status_map = {1: "indexed", 0: "pending", -1: "failed"}

    for r in rows:
        total += 1
        if r.embedded == 1:
            done += 1
        elif r.embedded == -1:
            failed += 1
        else:
            pending += 1
        docs.append(
            {
                "id": r.id,
                "filename": r.filename or f"document_{r.id}",
                "role": r.role,
                "status": status_map.get(r.embedded, "unknown"),
                "total_chunks": r.total_chunks or 0,
                "embedded_chunks": r.embedded_chunks or 0,
                "parser_used": r.parser_used,
                "last_error": r.last_error,
            }
        )

    return {
        "summary": {
            "total": total,
            "done": done,
            "failed": failed,
            "pending": pending,
            "complete": (pending == 0 and total > 0 and failed == 0),
        },
        "documents": docs,
    }


@router.post("/reindex")
async def reindex_system(
    user: dict = Depends(_require_clevel),
):
    """Queue a durable non-destructive full reindex across all active documents."""
    try:
        job_id, queued_docs = await enqueue_full_reindex_job(requested_by=user["username"])
        cache_manager.clear()
        return {
            "status": "ok",
            "job_id": job_id,
            "queued_docs": queued_docs,
            "pruned_orphan_docs": 0,
            "message": "Non-destructive reindex queued; existing vectors remain searchable while refreshed.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Re-indexing failed: {exc}") from exc


@router.post("/reindex-retry")
async def reindex_retry(
    user: dict = Depends(_require_clevel),
):
    try:
        job_id, queued_docs = await enqueue_retry_failed_job(requested_by=user["username"])
        return {
            "status": "ok",
            "job_id": job_id,
            "queued_docs": queued_docs,
            "message": "Retry queued — failed/pending docs re-queued for background workers.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retry failed: {exc}") from exc
