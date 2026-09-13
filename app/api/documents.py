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
def run_indexer():
    from app.rag.module import run_indexer as index
    return index()
from .auth import get_current_user
from .admin import _require_clevel

logger = logging.getLogger("FinSight.documents")
router = APIRouter(tags=["documents"])


@router.post("/upload-docs")
async def upload_docs(
    background_tasks: BackgroundTasks,
    file:  UploadFile = File(...),
    role:  str        = Form(...),
    user:  dict       = Depends(_require_clevel),
):
    """
    Upload a document (.md, .csv, .pdf), register it in SQLite,
    load CSV files into DuckDB, and kick off background indexing.
    """
    try:
        filename = file.filename or ""
        if not filename or any(c in filename for c in ('/', '\\', ':', '\x00')) or filename in {'.', '..'}:
            raise HTTPException(status_code=400, detail="Invalid filename.")
        conn = get_db_conn()
        try:
            role_row = conn.execute("SELECT role_name FROM roles WHERE LOWER(role_name)=LOWER(?)", (role.strip(),)).fetchone()
        finally:
            conn.close()
        if not role_row:
            raise HTTPException(status_code=400, detail="Select an existing access role.")
        role = role_row[0]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", role):
            raise HTTPException(status_code=400, detail="Role cannot be used as an upload directory.")
        extension = Path(filename).suffix.lower()

        if extension not in {".csv", ".md", ".pdf"}:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv, .md, or .pdf")

        base_upload_dir = Path(os.getenv("UPLOAD_DIR", str(UPLOAD_DIR)))
        role_dir  = base_upload_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)
        filepath = (role_dir / filename).resolve()
        if not filepath.is_relative_to(base_upload_dir.resolve()):
            raise HTTPException(status_code=400, detail="Invalid upload path.")
        if filepath.exists():
            raise HTTPException(status_code=409, detail="A file with this name already exists for this role. Rename the file before uploading.")

        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Files must be 20 MB or smaller.")
        if not data:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        if extension == '.pdf' and not data.startswith(b'%PDF-'):
            raise HTTPException(status_code=400, detail="The file is not a valid PDF.")

        headers_str: str | None = None
        if extension == ".csv":
            df          = pd.read_csv(BytesIO(data))
            tname       = re.sub(r"[^a-zA-Z0-9_]", "_", filepath.stem)
            if not tname or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", tname):
                raise HTTPException(status_code=400, detail="CSV filenames must start with a letter or underscore.")
            headers_str = ",".join(str(h) for h in df.columns.tolist())
            dc = duckdb.connect(str(DUCKDB_PATH))
            try:
                if dc.execute("SELECT 1 FROM information_schema.tables WHERE LOWER(table_name)=LOWER(?)", (tname,)).fetchone():
                    raise HTTPException(status_code=409, detail="A dataset with this name already exists. Use a unique CSV filename.")
                dc.register("df_tmp", df)
                dc.execute(f'CREATE TABLE "{tname}" AS SELECT * FROM df_tmp')
                dc.execute(
                    "INSERT INTO tables_metadata (table_name, role) VALUES (?,?)",
                    (tname, role),
                )
                dc.unregister("df_tmp")
            finally:
                dc.close()

        with filepath.open('xb') as destination:
            destination.write(data)
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
        raise HTTPException(status_code=500, detail="Upload could not be completed. Please contact your administrator.")


@router.get("/preview-pdf")
def preview_pdf(filepath: str, user: dict = Depends(get_current_user)):
    """Return only registered, authorized PDF documents using header authentication."""
    from fastapi.responses import FileResponse
    import sqlite3

    clean_path = str(Path(filepath).resolve())
    
    # Check if this document exists in SQLite and the user's role allows it
    from app.core.config import DB_PATH
    
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    
    user_role = user["role"].lower()
    if user_role == "c-level":
        c.execute("SELECT 1 FROM documents WHERE filepath IN (?,?)", (clean_path, filepath))
    elif user_role == "general":
        c.execute("SELECT 1 FROM documents WHERE filepath IN (?,?) AND LOWER(role)='general'", (clean_path, filepath))
    else:
        c.execute(
            "SELECT 1 FROM documents WHERE filepath IN (?,?) AND (LOWER(role)=? OR LOWER(role)='general')",
            (clean_path, filepath, user_role)
        )
    
    allowed = c.fetchone()
    conn.close()
    
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied to this file path.")
    if Path(clean_path).suffix.lower() != '.pdf':
        raise HTTPException(status_code=400, detail="Only PDF files can be opened here.")
            
    if not os.path.exists(clean_path):
        raise HTTPException(status_code=404, detail="PDF file not found.")
        
    return FileResponse(clean_path, media_type="application/pdf", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


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
        c.execute("SELECT 1 FROM documents WHERE filepath IN (?,?)", (clean_path, filepath))
    elif user_role == "general":
        c.execute("SELECT 1 FROM documents WHERE filepath IN (?,?) AND LOWER(role)='general'", (clean_path, filepath))
    else:
        c.execute(
            "SELECT 1 FROM documents WHERE filepath IN (?,?) AND (LOWER(role)=? OR LOWER(role)='general')",
            (clean_path, filepath, user_role)
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to read document")
        raise HTTPException(status_code=500, detail="The document could not be read.")


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
