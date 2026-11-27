"""
app/api/documents.py — Stateless document upload, streaming preview, and CRUD endpoints.
"""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
import logging
import math
import mimetypes
from pathlib import Path
import re
import uuid

import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz.openfga import get_rebac_service, normalize_subject
from app.core.audit import record_audit_event
from app.core.cache import cache_manager
from app.core.database import csv_bytes_to_parquet_bytes
from app.core.limiter import limiter
from app.db.models import (
    DatasetTable,
    DocumentChunk,
    DocumentRecord,
    JobRecord,
    Role,
    SemanticModel,
    User,
)
from app.db.session import get_db
from app.rag.semantic_layer import derive_starter_semantic_model
from app.storage import get_storage_backend
from app.workers.tasks import enqueue_document_index_job, invalidate_role_cache
from .admin import _require_clevel
from .auth import get_current_user

logger = logging.getLogger("FinSight.documents")
router = APIRouter(tags=["documents"])


def run_indexer():
    """Compatibility hook kept for existing unit tests monkeypatching `documents.run_indexer`."""
    from app.rag.module import run_indexer as index

    return index()


_DEFAULT_RUN_INDEXER = run_indexer


class DocumentRolePatchRequest(BaseModel):
    role: str


class DocumentPermissionGrantRequest(BaseModel):
    subject: str
    relation: str = "viewer"


async def _find_authorized_document(
    db: AsyncSession,
    user_role: str,
    *,
    username: str | None = None,
    doc_id: int | None = None,
    filepath: str | None = None,
) -> DocumentRecord | None:
    if doc_id is not None:
        stmt = select(DocumentRecord).where(DocumentRecord.id == doc_id)
    elif filepath:
        candidates = {filepath}
        try:
            candidates.add(str(Path(filepath).resolve()))
        except Exception:
            pass
        candidate_list = list(candidates)
        stmt = select(DocumentRecord).where(
            or_(
                DocumentRecord.object_key.in_(candidate_list),
                DocumentRecord.legacy_filepath.in_(candidate_list),
            )
        )
    else:
        return None

    doc = await db.scalar(stmt.limit(1))
    if doc is None:
        return None
    if username:
        allowed = await get_rebac_service().acheck_document_access(
            db, username=username, user_role=user_role, doc_id=doc.id
        )
        return doc if allowed else None
    role_lower = (user_role or "general").lower()
    if role_lower == "c-level" or doc.role.lower() == "general" or doc.role.lower() == role_lower:
        return doc
    return None


@router.post("/upload-docs")
@limiter.limit("10/minute")
async def upload_docs(
    request: Request,
    file: UploadFile = File(...),
    role: str = Form(...),
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document (.md, .csv, .pdf), persist raw bytes (plus Parquet for CSV)
    into ObjectStorageBackend, register metadata in Postgres, and dispatch Taskiq job.
    """
    storage = get_storage_backend()
    uploaded_object_key: str | None = None
    uploaded_parquet_key: str | None = None

    try:
        filename = file.filename or ""
        if (
            not filename
            or any(c in filename for c in ("/", "\\", ":", "\x00"))
            or filename in {".", ".."}
        ):
            raise HTTPException(status_code=400, detail="Invalid filename.")

        role_row = await db.scalar(
            select(Role).where(func.lower(Role.role_name) == role.strip().lower())
        )
        if role_row is None:
            raise HTTPException(status_code=400, detail="Select an existing access role.")
        canonical_role = role_row.role_name
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", canonical_role):
            raise HTTPException(
                status_code=400, detail="Role cannot be used as an upload namespace."
            )

        extension = Path(filename).suffix.lower()
        if extension not in {".csv", ".md", ".pdf"}:
            raise HTTPException(
                status_code=400, detail="Unsupported file type. Use .csv, .md, or .pdf"
            )

        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Files must be 20 MB or smaller.")
        if not data:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        if extension == ".pdf" and not data.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="The file is not a valid PDF.")

        existing_doc = await db.scalar(
            select(DocumentRecord).where(
                func.lower(DocumentRecord.role) == canonical_role.lower(),
                func.lower(DocumentRecord.filename) == filename.lower(),
            )
        )
        if existing_doc is not None:
            raise HTTPException(
                status_code=409,
                detail="A file with this name already exists for this role. Rename the file before uploading.",
            )

        headers_str: str | None = None
        parquet_info: tuple[str, bytes, list[str], int] | None = None
        if extension == ".csv":
            tname = re.sub(r"[^a-zA-Z0-9_]", "_", Path(filename).stem)
            if not tname or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", tname):
                raise HTTPException(
                    status_code=400,
                    detail="CSV filenames must start with a letter or underscore.",
                )
            existing_table = await db.scalar(
                select(DatasetTable).where(
                    func.lower(DatasetTable.table_name) == tname.lower()
                )
            )
            if existing_table is not None:
                raise HTTPException(
                    status_code=409,
                    detail="A dataset with this name already exists. Use a unique CSV filename.",
                )
            parquet_bytes, cols, row_count = await asyncio.to_thread(
                csv_bytes_to_parquet_bytes, data
            )
            headers_str = ",".join(cols)
            parquet_info = (tname, parquet_bytes, cols, row_count)

        content_type = (
            file.content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        sha256 = hashlib.sha256(data).hexdigest()

        await storage.aensure_bucket()
        uploaded_object_key = await storage.aput_bytes(
            f"documents/{canonical_role}/{uuid.uuid4().hex}_{filename}",
            data,
            content_type=content_type,
        )

        doc = DocumentRecord(
            filename=filename,
            role=canonical_role,
            object_key=uploaded_object_key,
            legacy_filepath=None,
            content_type=content_type,
            size_bytes=len(data),
            sha256=sha256,
            headers_str=headers_str,
            embedded=0,
            total_chunks=0,
            embedded_chunks=0,
        )
        db.add(doc)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="A file with this name already exists for this role.",
            ) from exc

        rebac = get_rebac_service()
        await rebac.async_document_tuples(
            db,
            doc.id,
            canonical_role,
            owner_username=user["username"],
            created_by=user["username"],
        )

        if parquet_info is not None:
            tname, parquet_bytes, cols, row_count = parquet_info
            uploaded_parquet_key = await storage.aput_bytes(
                f"datasets/{canonical_role}/{doc.id}/{tname}.parquet",
                parquet_bytes,
                content_type="application/vnd.apache.parquet",
            )
            db.add(
                DatasetTable(
                    doc_id=doc.id,
                    table_name=tname,
                    role=canonical_role,
                    parquet_key=uploaded_parquet_key,
                    columns_json=cols,
                    row_count=row_count,
                )
            )
            await rebac.async_dataset_tuples(
                db,
                doc.id,
                tname,
                owner_username=user["username"],
                created_by=user["username"],
            )
            existing_sm = await db.scalar(
                select(SemanticModel).where(func.lower(SemanticModel.table_name) == tname.lower())
            )
            if existing_sm is None:
                starter = derive_starter_semantic_model(
                    tname, columns=cols, parquet_bytes=parquet_bytes
                )
                db.add(
                    SemanticModel(
                        table_name=tname,
                        doc_id=doc.id,
                        display_name=starter["display_name"],
                        description=starter["description"],
                        metrics_json=starter["metrics"],
                        dimensions_json=starter["dimensions"],
                        synonyms_json=starter["synonyms"],
                        joins_json=starter["joins"],
                        updated_by=user["username"],
                    )
                )

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Document or dataset conflict during registration.",
            ) from exc

        job_id: str | None = None
        if run_indexer is _DEFAULT_RUN_INDEXER:
            job_id, _ = await enqueue_document_index_job(
                doc.id, requested_by=user["username"]
            )
        else:
            run_indexer()

        invalidate_role_cache(canonical_role)
        await record_audit_event(
            username=user["username"],
            user_role=user["role"],
            auth_provider=user.get("auth_provider", "local"),
            event_type="document_upload",
            authorized_doc_count=1,
            cited_doc_ids=[doc.id],
            outcome="allow",
            raw_prompt=f"upload:{filename} role={canonical_role}",
            ai_disclosure=False,
        )

        return JSONResponse(
            content={
                "message": f"'{filename}' uploaded for role '{canonical_role}'. Indexing started.",
                "doc_id": doc.id,
                "object_key": doc.object_key,
                "job_id": job_id,
            }
        )

    except HTTPException:
        if uploaded_object_key:
            await storage.adelete(uploaded_object_key)
        if uploaded_parquet_key:
            await storage.adelete(uploaded_parquet_key)
        raise
    except Exception as exc:
        if uploaded_object_key:
            await storage.adelete(uploaded_object_key)
        if uploaded_parquet_key:
            await storage.adelete(uploaded_parquet_key)
        logger.error(f"[UPLOAD] Failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Upload could not be completed. Please contact your administrator.",
        ) from exc


@router.get("/preview-pdf")
async def preview_pdf(
    doc_id: int | None = Query(default=None),
    filepath: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return authorized registered PDF bytes directly from ObjectStorageBackend."""
    if doc_id is None and not filepath:
        raise HTTPException(status_code=400, detail="Provide 'doc_id' or 'filepath'.")

    doc = await _find_authorized_document(
        db,
        user["role"],
        username=user["username"],
        doc_id=doc_id,
        filepath=filepath,
    )
    if doc is None:
        raise HTTPException(status_code=403, detail="Access denied to this file path.")
    if Path(doc.filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files can be opened here.")

    storage = get_storage_backend()
    try:
        raw_bytes = await storage.aget_bytes(doc.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PDF file not found.") from exc

    return Response(
        content=raw_bytes,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{doc.filename}"',
        },
    )


@router.get("/documents")
async def list_documents(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed_ids = await get_rebac_service().alist_authorized_doc_ids(
        db, username=user["username"], user_role=user["role"]
    )
    if not allowed_ids:
        return []
    stmt = (
        select(DocumentRecord)
        .where(DocumentRecord.id.in_(allowed_ids))
        .order_by(DocumentRecord.id.asc())
    )
    rows = list(await db.scalars(stmt))
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "filepath": r.legacy_filepath or r.object_key,
            "object_key": r.object_key,
            "role": r.role,
            "headers_str": r.headers_str,
            "embedded": r.embedded,
            "parser_used": r.parser_used,
            "size_bytes": r.size_bytes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/documents/content")
async def get_document_content(
    doc_id: int | None = Query(default=None),
    filepath: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if doc_id is None and not filepath:
        raise HTTPException(status_code=400, detail="Provide 'doc_id' or 'filepath'.")

    doc = await _find_authorized_document(
        db,
        user["role"],
        username=user["username"],
        doc_id=doc_id,
        filepath=filepath,
    )
    if doc is None:
        raise HTTPException(status_code=403, detail="Access denied to this file path.")

    storage = get_storage_backend()
    try:
        raw_bytes = await storage.aget_bytes(doc.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc

    ext = Path(doc.filename).suffix.lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(BytesIO(raw_bytes))

            def _safe(val):
                if val is None:
                    return None
                if isinstance(val, float):
                    if math.isnan(val) or math.isinf(val):
                        return None
                    return val
                try:
                    if pd.isna(val):
                        return None
                except (TypeError, ValueError):
                    pass
                return val

            columns = df.columns.tolist()
            total_rows = len(df)
            sliced_df = df.iloc[offset : offset + limit]
            data = [
                {col: _safe(row[col]) for col in columns}
                for row in sliced_df.to_dict(orient="records")
            ]
            return JSONResponse(
                content={
                    "type": "csv",
                    "columns": columns,
                    "data": data,
                    "total_rows": total_rows,
                    "offset": offset,
                    "limit": limit,
                    "truncated": (offset + len(data)) < total_rows,
                }
            )
        if ext == ".md":
            return {"type": "markdown", "content": raw_bytes.decode("utf-8", errors="replace")}
        raise HTTPException(
            status_code=400, detail="Previewing this file type is not supported."
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read document content")
        raise HTTPException(
            status_code=500, detail="The document could not be read."
        ) from exc


@router.patch("/documents/{doc_id}")
async def update_document_role(
    doc_id: int,
    body: DocumentRolePatchRequest,
    current_admin: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    role_row = await db.scalar(
        select(Role).where(func.lower(Role.role_name) == body.role.strip().lower())
    )
    if role_row is None:
        raise HTTPException(status_code=400, detail="Invalid target role.")

    old_role = doc.role
    new_role = role_row.role_name
    if old_role.lower() == new_role.lower():
        return {
            "id": doc.id,
            "filename": doc.filename,
            "role": doc.role,
            "message": "Document role unchanged.",
        }

    collision = await db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.id != doc_id,
            func.lower(DocumentRecord.role) == new_role.lower(),
            func.lower(DocumentRecord.filename) == doc.filename.lower(),
        )
    )
    if collision is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Role '{new_role}' already has a document named '{doc.filename}'.",
        )

    doc.role = new_role
    await db.execute(
        update(DocumentChunk)
        .where(DocumentChunk.doc_id == doc_id)
        .values(role=new_role.lower())
    )
    await db.execute(
        update(DatasetTable)
        .where(DatasetTable.doc_id == doc_id)
        .values(role=new_role)
    )
    await get_rebac_service().async_document_tuples(
        db,
        doc_id,
        new_role,
        previous_role=old_role,
        created_by=current_admin["username"],
    )
    await db.commit()

    invalidate_role_cache(old_role)
    invalidate_role_cache(new_role)
    cache_manager.clear()
    await record_audit_event(
        username=current_admin["username"],
        user_role=current_admin["role"],
        auth_provider=current_admin.get("auth_provider", "local"),
        event_type="document_role_change",
        cited_doc_ids=[doc.id],
        outcome="allow",
        raw_prompt=f"reassign:{doc.filename} {old_role}->{new_role}",
        ai_disclosure=False,
    )

    return {
        "id": doc.id,
        "filename": doc.filename,
        "role": new_role,
        "message": f"Reassigned '{doc.filename}' to '{new_role}'.",
    }


@router.post("/documents/{doc_id}/reindex")
async def reindex_single_document(
    doc_id: int,
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    doc.embedded = 0
    doc.embedded_chunks = 0
    doc.last_error = None
    await db.commit()

    job_id, _ = await enqueue_document_index_job(doc_id, requested_by=user["username"])
    return {
        "status": "ok",
        "doc_id": doc_id,
        "job_id": job_id,
        "message": f"Reindex queued for '{doc.filename}'.",
    }


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    running_job = await db.scalar(
        select(JobRecord).where(
            JobRecord.target_doc_id == doc_id,
            JobRecord.status.in_(["running", "cancel_requested"]),
        )
    )
    if running_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Document has an active running indexing job. Cancel the job before deleting.",
        )

    await db.execute(
        update(JobRecord)
        .where(JobRecord.target_doc_id == doc_id, JobRecord.status == "queued")
        .values(status="cancelled", progress_message="Document deleted before execution.")
    )

    ds_rows = (
        await db.execute(
            select(DatasetTable.parquet_key, DatasetTable.table_name).where(
                DatasetTable.doc_id == doc_id
            )
        )
    ).all()
    parquet_keys = [r[0] for r in ds_rows]
    dataset_names = [r[1] for r in ds_rows]
    object_key = doc.object_key
    role = doc.role
    filename = doc.filename

    await get_rebac_service().adelete_document_tuples(
        db, doc_id, dataset_names=dataset_names
    )
    await db.delete(doc)
    await db.commit()

    storage = get_storage_backend()
    if object_key:
        await storage.adelete(object_key)
    for pkey in parquet_keys:
        if pkey:
            await storage.adelete(pkey)

    invalidate_role_cache(role)
    cache_manager.clear()
    await record_audit_event(
        username=_user["username"],
        user_role=_user["role"],
        auth_provider=_user.get("auth_provider", "local"),
        event_type="document_delete",
        cited_doc_ids=[doc_id],
        outcome="allow",
        raw_prompt=f"delete:{filename} role={role}",
        ai_disclosure=False,
    )
    return {"message": f"Document '{filename}' deleted."}


# ── ReBAC Document Permissions (Per-User / Cross-Role Sharing) ────────────────


@router.get("/documents/{doc_id}/permissions")
async def get_document_permissions(
    doc_id: int,
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    permissions = await get_rebac_service().alist_document_permissions(db, doc_id)
    return {
        "doc_id": doc.id,
        "filename": doc.filename,
        "role": doc.role,
        "permissions": permissions,
    }


@router.post("/documents/{doc_id}/permissions")
async def grant_document_permission(
    doc_id: int,
    body: DocumentPermissionGrantRequest,
    current_admin: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        clean_subject = normalize_subject(body.subject)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if clean_subject.startswith("user:"):
        target_uname = clean_subject.split(":", 1)[1]
        u = await db.scalar(select(User).where(func.lower(User.username) == target_uname))
        if u is None:
            raise HTTPException(status_code=404, detail=f"User '{target_uname}' not found.")
    elif clean_subject.startswith("role:"):
        target_rname = clean_subject.split(":", 1)[1].split("#", 1)[0]
        r = await db.scalar(select(Role).where(func.lower(Role.role_name) == target_rname))
        if r is None:
            raise HTTPException(status_code=404, detail=f"Role '{target_rname}' not found.")

    try:
        grant = await get_rebac_service().agrant_permission(
            db,
            subject=clean_subject,
            relation=body.relation,
            object_type="document",
            object_id=str(doc_id),
            created_by=current_admin["username"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    cache_manager.clear()
    await record_audit_event(
        username=current_admin["username"],
        user_role=current_admin["role"],
        auth_provider=current_admin.get("auth_provider", "local"),
        event_type="rebac_acl_change",
        cited_doc_ids=[doc_id],
        outcome="allow",
        raw_prompt=f"grant:{clean_subject} {body.relation} doc={doc_id}",
        ai_disclosure=False,
    )
    permissions = await get_rebac_service().alist_document_permissions(db, doc_id)
    return {"grant": grant, "permissions": permissions}


@router.delete("/documents/{doc_id}/permissions")
async def revoke_document_permission(
    doc_id: int,
    subject: str = Query(...),
    relation: str = Query("viewer"),
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.scalar(select(DocumentRecord).where(DocumentRecord.id == doc_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        clean_subject = normalize_subject(subject)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if relation.strip().lower() in {"admin_role", "parent_role"}:
        raise HTTPException(
            status_code=400,
            detail="Use PATCH /documents/{doc_id} to change primary department role assignments.",
        )

    removed = await get_rebac_service().arevoke_permission(
        db,
        subject=clean_subject,
        relation=relation,
        object_type="document",
        object_id=str(doc_id),
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Permission grant not found.")
    await db.commit()
    cache_manager.clear()
    await record_audit_event(
        username=_user["username"],
        user_role=_user["role"],
        auth_provider=_user.get("auth_provider", "local"),
        event_type="rebac_acl_change",
        cited_doc_ids=[doc_id],
        outcome="allow",
        raw_prompt=f"revoke:{clean_subject} {relation} doc={doc_id}",
        ai_disclosure=False,
    )
    permissions = await get_rebac_service().alist_document_permissions(db, doc_id)
    return {"message": "Permission revoked.", "permissions": permissions}


@router.get("/system-metrics")
async def get_system_metrics(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user["role"].lower() != "c-level":
        raise HTTPException(status_code=403, detail="Access restricted to C-Level users.")
    metrics = {"docs": 0, "users": 0, "roles": 0, "tables": 0, "active_jobs": 0}
    try:
        metrics["docs"] = int(
            await db.scalar(select(func.count()).select_from(DocumentRecord)) or 0
        )
        metrics["users"] = int(
            await db.scalar(select(func.count()).select_from(User)) or 0
        )
        metrics["roles"] = int(
            await db.scalar(select(func.count()).select_from(Role)) or 0
        )
        metrics["tables"] = int(
            await db.scalar(select(func.count()).select_from(DatasetTable)) or 0
        )
        metrics["active_jobs"] = int(
            await db.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.status.in_(["queued", "running", "cancel_requested"]))
            )
            or 0
        )
    except Exception as exc:
        logger.warning(f"Failed to fetch system metrics: {exc}")
    return metrics
