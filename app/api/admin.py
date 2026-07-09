"""
app/api/admin.py — User & role management endpoints (C-Level only).

Handles:
  GET  /roles
  POST /create-user
  POST /create-role
  GET  /reindex-status
  GET  /reindex-details
  POST /reindex
  POST /reindex-retry
  GET  /indexing-status
  GET  /indexing-status-bulk
"""

import sqlite3
import logging

from fastapi import APIRouter, Depends, HTTPException, Form

from app.core.database import get_db_conn
from app.core.security import hash_password
from .auth import get_current_user

logger = logging.getLogger("FinSight.admin")
router = APIRouter(tags=["admin"])

_CLEVEL = "c-level"


def _require_clevel(user: dict = Depends(get_current_user)) -> dict:
    if user["role"].lower() != _CLEVEL:
        raise HTTPException(status_code=403, detail="Only C-Level users can perform this action.")
    return user


# ── Roles ─────────────────────────────────────────────────────────────────────
@router.get("/roles")
def get_roles(user: dict = Depends(get_current_user)):
    conn  = get_db_conn()
    roles = [r[0] for r in conn.execute("SELECT role_name FROM roles").fetchall()]
    conn.close()
    return {"roles": roles}


@router.post("/create-role")
def create_role(
    role_name: str = Form(...),
    user: dict = Depends(_require_clevel),
):
    conn = get_db_conn()
    try:
        conn.execute("INSERT INTO roles (role_name) VALUES (?)", (role_name.strip(),))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Role already exists")
    conn.close()
    return {"message": f"Role '{role_name}' created."}


# ── Users ─────────────────────────────────────────────────────────────────────
@router.post("/create-user")
def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role:     str = Form(...),
    user: dict = Depends(_require_clevel),
):
    conn = get_db_conn()
    c    = conn.cursor()
    c.execute("SELECT 1 FROM roles WHERE LOWER(role_name)=LOWER(?)", (role,))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid role")
    try:
        c.execute(
            "INSERT INTO users (username, password, role) VALUES (?,?,?)",
            (username.strip(), hash_password(password.strip()), role.strip()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="User already exists")
    conn.close()
    return {"message": f"User '{username}' created with role '{role}'."}


# ── Indexing status ───────────────────────────────────────────────────────────
@router.get("/indexing-status")
def get_indexing_status(filename: str, user: dict = Depends(get_current_user)):
    """Per-file status — used by the upload progress bar."""
    conn = get_db_conn()
    row  = conn.execute(
        "SELECT embedded, total_chunks, embedded_chunks FROM documents "
        "WHERE filename=? ORDER BY id DESC LIMIT 1",
        (filename,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"embedded": row[0], "total_chunks": row[1], "embedded_chunks": row[2]}


@router.get("/indexing-status-bulk")
def get_indexing_status_bulk(user: dict = Depends(_require_clevel)):
    """
    Return aggregated + per-document indexing status in a single DB query.
    Used by the admin dashboard for efficient polling.
    """
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, filename, role, embedded, total_chunks, embedded_chunks "
        "FROM documents ORDER BY embedded ASC, id ASC"
    ).fetchall()
    conn.close()

    total = done = failed = pending = 0
    docs: list[dict] = []
    status_map = {1: "indexed", 0: "pending", -1: "failed"}

    for r in rows:
        total += 1
        if r["embedded"] == 1:    done    += 1
        elif r["embedded"] == -1: failed  += 1
        else:                     pending += 1
        docs.append({
            "id":              r["id"],
            "filename":        r["filename"] or f"document_{r['id']}",
            "role":            r["role"],
            "status":          status_map.get(r["embedded"], "unknown"),
            "total_chunks":    r["total_chunks"]    or 0,
            "embedded_chunks": r["embedded_chunks"] or 0,
        })

    return {
        "summary": {
            "total":    total,
            "done":     done,
            "failed":   failed,
            "pending":  pending,
            "complete": (pending == 0 and total > 0 and failed == 0),
        },
        "documents": docs,
    }


# ── Legacy separate reindex status endpoints (backward-compat) ────────────────
@router.get("/reindex-status")
def reindex_status(user: dict = Depends(_require_clevel)):
    conn    = get_db_conn()
    c       = conn.cursor()
    total   = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    done    = c.execute("SELECT COUNT(*) FROM documents WHERE embedded=1").fetchone()[0]
    failed  = c.execute("SELECT COUNT(*) FROM documents WHERE embedded=-1").fetchone()[0]
    pending = c.execute("SELECT COUNT(*) FROM documents WHERE embedded=0").fetchone()[0]
    conn.close()
    return {
        "total": total, "done": done, "failed": failed, "pending": pending,
        "complete": (pending == 0 and total > 0),
    }


@router.get("/reindex-details")
def reindex_details(user: dict = Depends(_require_clevel)):
    conn = get_db_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, filename, role, embedded, total_chunks, embedded_chunks "
        "FROM documents ORDER BY embedded ASC, id ASC"
    ).fetchall()
    conn.close()
    status_map = {1: "indexed", 0: "pending", -1: "failed"}
    return {"documents": [{
        "id":              r["id"],
        "filename":        r["filename"] or f"document_{r['id']}",
        "role":            r["role"],
        "status":          status_map.get(r["embedded"], "unknown"),
        "total_chunks":    r["total_chunks"]    or 0,
        "embedded_chunks": r["embedded_chunks"] or 0,
    } for r in rows]}


# ── Reindex actions ───────────────────────────────────────────────────────────
@router.post("/reindex")
def reindex_system(user: dict = Depends(_require_clevel)):
    """Full wipe + rebuild of the vector store."""
    try:
        from app.rag.module import _reset_databases, _reinit_vectorstore, trigger_indexing
        _reset_databases("admin reindex request")
        _reinit_vectorstore()
        trigger_indexing()
        return {"message": "Vector store wiped. All documents queued for re-embedding."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Re-indexing failed: {exc}")


@router.post("/reindex-retry")
def reindex_retry(user: dict = Depends(_require_clevel)):
    try:
        from app.rag.module import trigger_retry_pending
        trigger_retry_pending()
        return {"message": "Retry started — failed/pending docs re-queued."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retry failed: {exc}")
