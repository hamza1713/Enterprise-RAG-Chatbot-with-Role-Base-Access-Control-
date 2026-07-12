"""
app/api/documents.py — Document upload & management endpoints.

Handles:  POST /upload-docs
"""

import os
import re
import logging
from pathlib import Path
from io import BytesIO

import duckdb
import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import DUCKDB_PATH, UPLOAD_DIR
from app.core.database import get_db_conn
from app.rag.module import run_indexer
from .auth import get_current_user

logger = logging.getLogger("FinSight.documents")
router = APIRouter(tags=["documents"])


@router.post("/upload-docs")
async def upload_docs(
    background_tasks: BackgroundTasks,
    file:  UploadFile = File(...),
    role:  str        = Form(...),
    user:  dict       = Depends(get_current_user),
):
    """
    Upload a document (.md, .csv, .pdf), register it in SQLite,
    load CSV files into DuckDB, and kick off background indexing.
    """
    try:
        filename  = file.filename
        extension = Path(filename).suffix.lower()

        if extension not in {".csv", ".md", ".pdf"}:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv, .md, or .pdf")

        role_dir  = UPLOAD_DIR / role
        role_dir.mkdir(parents=True, exist_ok=True)
        filepath  = role_dir / filename

        data = await file.read()
        filepath.write_bytes(data)

        headers_str: str | None = None
        if extension == ".csv":
            df          = pd.read_csv(BytesIO(data))
            tname       = re.sub(r"[^a-zA-Z0-9_]", "_", filepath.stem)
            headers_str = ",".join(str(h) for h in df.columns.tolist())
            dc = duckdb.connect(str(DUCKDB_PATH))
            try:
                dc.execute("DELETE FROM tables_metadata WHERE table_name=?", (tname,))
                dc.register("df_tmp", df)
                dc.execute(f"CREATE OR REPLACE TABLE {tname} AS SELECT * FROM df_tmp")
                dc.execute(
                    "INSERT INTO tables_metadata (table_name, role) VALUES (?,?)",
                    (tname, role),
                )
                dc.unregister("df_tmp")
            finally:
                dc.close()

        conn = get_db_conn()
        conn.execute(
            "INSERT INTO documents "
            "(filename, role, filepath, headers_str, embedded, total_chunks, embedded_chunks) "
            "VALUES (?,?,?,?,0,0,0)",
            (filename, role, str(filepath), headers_str),
        )
        conn.commit()
        conn.close()

        background_tasks.add_task(run_indexer)

        return JSONResponse(content={
            "message": f"'{filename}' uploaded for role '{role}'. Indexing started."
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[UPLOAD] Failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Query

_bearer = HTTPBearer(auto_error=False)


@router.get("/preview-pdf")
def preview_pdf(
    filepath: str,
    token: str | None = Query(None),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
):
    """
    Securely preview a PDF file. Verifies the user has role-based access
    to the document, and returns the file response.
    Supports authenticating via query parameter `token` or bearer header.
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    from app.core.security import decode_access_token
    import sqlite3
    
    # Resolve token from header or query param
    resolved_token = None
    if creds:
        resolved_token = creds.credentials
    elif token:
        resolved_token = token
        
    if not resolved_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    try:
        payload  = decode_access_token(resolved_token)
        username = payload.get("sub")
        role     = payload.get("role")
        if not username or not role:
            raise HTTPException(status_code=401, detail="Invalid token payload.")
        user = {"username": username, "role": role}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    clean_path = str(Path(filepath).resolve())
    
    # Check if this document exists in SQLite and the user's role allows it
    from app.core.config import DB_PATH
    
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    user_role = user["role"].lower()
    if user_role == "c-level":
        c.execute("SELECT 1 FROM documents WHERE filepath=?", (clean_path,))
    elif user_role == "general":
        c.execute("SELECT 1 FROM documents WHERE filepath=? AND LOWER(role)='general'", (clean_path,))
    else:
        c.execute(
            "SELECT 1 FROM documents WHERE filepath=? AND (LOWER(role)=? OR LOWER(role)='general')",
            (clean_path, user_role)
        )
    
    allowed = c.fetchone()
    conn.close()
    
    if not allowed:
        # Fallback security check: is it in UPLOAD_DIR or RESOURCES_DIR?
        from app.core.config import UPLOAD_DIR, RESOURCES_DIR
        try:
            p = Path(clean_path)
            is_under_uploads = p.is_relative_to(UPLOAD_DIR)
            is_under_resources = p.is_relative_to(RESOURCES_DIR)
        except AttributeError:
            is_under_uploads = str(clean_path).startswith(str(UPLOAD_DIR))
            is_under_resources = str(clean_path).startswith(str(RESOURCES_DIR))
            
        if not (is_under_uploads or is_under_resources):
            raise HTTPException(status_code=403, detail="Access denied to this file path.")
            
    if not os.path.exists(clean_path):
        raise HTTPException(status_code=404, detail="PDF file not found.")
        
    return FileResponse(clean_path, media_type="application/pdf")


@router.get("/documents")
def list_documents(user: dict = Depends(get_current_user)):
    user_role = user["role"].lower()
    conn = get_db_conn()
    c = conn.cursor()
    if user_role == "c-level":
        c.execute("SELECT filename, filepath FROM documents")
    elif user_role == "general":
        c.execute("SELECT filename, filepath FROM documents WHERE LOWER(role)='general'")
    else:
        c.execute(
            "SELECT filename, filepath FROM documents WHERE LOWER(role)=? OR LOWER(role)='general'",
            (user_role,),
        )
    rows = c.fetchall()
    conn.close()
    return [{"filename": r[0], "filepath": r[1]} for r in rows]


@router.get("/documents/content")
def get_document_content(filepath: str, user: dict = Depends(get_current_user)):
    user_role = user["role"].lower()
    clean_path = str(Path(filepath).resolve())
    
    # RBAC check
    conn = get_db_conn()
    c = conn.cursor()
    if user_role == "c-level":
        c.execute("SELECT 1 FROM documents WHERE filepath=?", (clean_path,))
    elif user_role == "general":
        c.execute("SELECT 1 FROM documents WHERE filepath=? AND LOWER(role)='general'", (clean_path,))
    else:
        c.execute(
            "SELECT 1 FROM documents WHERE filepath=? AND (LOWER(role)=? OR LOWER(role)='general')",
            (clean_path, user_role)
        )
    allowed = c.fetchone()
    conn.close()
    
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied to this file path.")
        
    if not os.path.exists(clean_path):
        raise HTTPException(status_code=404, detail="File not found.")
        
    ext = os.path.splitext(clean_path)[1].lower()
    try:
        if ext == ".csv":
            import math
            df = pd.read_csv(clean_path)

            def _safe(val):
                """Convert any non-JSON-safe value to None."""
                if val is None:
                    return None
                if isinstance(val, float):
                    if math.isnan(val) or math.isinf(val):
                        return None
                    return val
                # pandas NA / NaT
                try:
                    if pd.isna(val):
                        return None
                except (TypeError, ValueError):
                    pass
                return val

            columns = df.columns.tolist()
            data = [
                {col: _safe(row[col]) for col in columns}
                for row in df.to_dict(orient="records")
            ]
            return JSONResponse(content={
                "type": "csv",
                "columns": columns,
                "data": data,
            })
        elif ext == ".md":
            with open(clean_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"type": "markdown", "content": content}
        else:
            raise HTTPException(status_code=400, detail="Previewing this file type is not supported.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")


@router.get("/system-metrics")
def get_system_metrics(user: dict = Depends(get_current_user)):
    if user["role"].lower() != "c-level":
        raise HTTPException(status_code=403, detail="Access restricted to C-Level users.")
    metrics = {"docs": 0, "users": 0, "roles": 0, "tables": 0}
    try:
        conn = get_db_conn()
        c = conn.cursor()
        metrics["docs"]  = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        metrics["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        metrics["roles"] = c.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
        conn.close()
        
        from app.core.config import DUCKDB_PATH
        dc = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        metrics["tables"] = dc.execute("SELECT COUNT(*) FROM tables_metadata").fetchone()[0]
        dc.close()
    except Exception as exc:
        logger.warning(f"Failed to fetch system metrics: {exc}")
    return metrics

