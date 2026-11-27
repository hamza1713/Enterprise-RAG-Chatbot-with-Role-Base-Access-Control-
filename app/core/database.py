"""
app/core/database.py — PostgreSQL seeding helpers and Parquet CSV serialization.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
import logging
import mimetypes
from pathlib import Path
import re
import uuid

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import func, select, text

from app.authz.openfga import get_rebac_service
from app.core.config import RESOURCES_DIR
from app.core.users import _SYSTEM_ROLES, seed_default_users
from app.db.models import DatasetTable, DocumentRecord, JobRecord, Role
from app.db.session import sync_session
from app.rag.semantic_layer import ensure_starter_semantic_model_sync
from app.storage import get_storage_backend

logger = logging.getLogger("FinSight.db")

_ROLE_MAPPING: dict[str, str] = {
    "engineering": "Engineering",
    "finance":     "Finance",
    "general":     "General",
    "hr":          "HR",
    "marketing":   "Marketing",
}


def sanitize_table_name(filename: str) -> str:
    """Convert a CSV filename stem into a validated SQL identifier."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", Path(filename).stem)


def csv_bytes_to_parquet_bytes(data: bytes) -> tuple[bytes, list[str], int]:
    """
    Parse CSV bytes via Pandas and serialize them as compressed Parquet bytes.
    Returns (parquet_bytes, column_names, row_count).
    """
    df = pd.read_csv(BytesIO(data))
    columns = [str(col) for col in df.columns.tolist()]
    table = pa.Table.from_pandas(df, preserve_index=False)
    out = BytesIO()
    pq.write_table(table, out, compression="snappy")
    return out.getvalue(), columns, int(len(df))


def init_postgres_seed() -> None:
    """Verify PostgreSQL connectivity and idempotently seed roles/users."""
    with sync_session() as db:
        db.execute(text("SELECT 1"))
    seed_default_users()


def preload_default_data() -> list[tuple[str, int]]:
    """
    Upload sample documents from resources/data/<dept>/ to ObjectStorageBackend,
    persist Parquet datasets for CSVs, register rows in PostgreSQL, and enqueue
    durable indexing jobs for unindexed files.

    Returns list of (job_id, doc_id) created for newly registered documents.
    """
    if not RESOURCES_DIR.exists():
        return []

    storage = get_storage_backend()
    storage.ensure_bucket()
    created_jobs: list[tuple[str, int]] = []

    with sync_session() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(724902)"))

        for role_name in _ROLE_MAPPING.values():
            existing_role = db.scalar(
                select(Role).where(func.lower(Role.role_name) == role_name.lower())
            )
            if existing_role is None:
                db.add(
                    Role(
                        role_name=role_name,
                        is_system=role_name.lower() in _SYSTEM_ROLES,
                    )
                )
        db.flush()

        for sub in RESOURCES_DIR.iterdir():
            if not sub.is_dir():
                continue
            role = _ROLE_MAPPING.get(sub.name.lower(), sub.name.capitalize())

            for filepath in sorted(sub.iterdir()):
                if not filepath.is_file():
                    continue
                filename = filepath.name
                extension = filepath.suffix.lower()
                if extension not in {".csv", ".md", ".pdf"}:
                    continue

                existing_doc = db.scalar(
                    select(DocumentRecord).where(
                        func.lower(DocumentRecord.filename) == filename.lower(),
                        func.lower(DocumentRecord.role) == role.lower(),
                    )
                )
                if existing_doc is not None:
                    continue

                raw_bytes = filepath.read_bytes()
                if not raw_bytes:
                    continue

                sha256 = hashlib.sha256(raw_bytes).hexdigest()
                content_type = mimetypes.guess_type(filename)[0] or (
                    "text/csv"
                    if extension == ".csv"
                    else "text/markdown"
                    if extension == ".md"
                    else "application/pdf"
                )
                object_key = storage.put_bytes(
                    f"documents/{role}/{uuid.uuid4().hex}_{filename}",
                    raw_bytes,
                    content_type=content_type,
                )

                headers_str: str | None = None
                parquet_info: tuple[str, bytes, list[str], int] | None = None

                if extension == ".csv":
                    try:
                        tname = re.sub(r"[^a-zA-Z0-9_]", "_", filepath.stem)
                        parquet_bytes, cols, row_count = csv_bytes_to_parquet_bytes(raw_bytes)
                        headers_str = ",".join(cols)
                        parquet_info = (tname, parquet_bytes, cols, row_count)
                    except Exception as exc:
                        logger.error(f"[PRELOAD] CSV parse failed for {filename}: {exc}")

                doc = DocumentRecord(
                    filename=filename,
                    role=role,
                    object_key=object_key,
                    legacy_filepath=None,
                    content_type=content_type,
                    size_bytes=len(raw_bytes),
                    sha256=sha256,
                    headers_str=headers_str,
                    embedded=0,
                    total_chunks=0,
                    embedded_chunks=0,
                )
                db.add(doc)
                db.flush()
                rebac = get_rebac_service()
                rebac.sync_document_tuples(
                    db,
                    doc.id,
                    role,
                    owner_username="admin",
                    created_by="preload",
                )

                if parquet_info is not None:
                    tname, parquet_bytes, cols, row_count = parquet_info
                    existing_table = db.scalar(
                        select(DatasetTable).where(
                            func.lower(DatasetTable.table_name) == tname.lower()
                        )
                    )
                    if existing_table is None:
                        parquet_key = storage.put_bytes(
                            f"datasets/{role}/{doc.id}/{tname}.parquet",
                            parquet_bytes,
                            content_type="application/vnd.apache.parquet",
                        )
                        db.add(
                            DatasetTable(
                                doc_id=doc.id,
                                table_name=tname,
                                role=role,
                                parquet_key=parquet_key,
                                columns_json=cols,
                                row_count=row_count,
                            )
                        )
                        rebac.sync_dataset_tuples(
                            db,
                            doc.id,
                            tname,
                            owner_username="admin",
                            created_by="preload",
                        )
                        ensure_starter_semantic_model_sync(
                            db,
                            table_name=tname,
                            doc_id=doc.id,
                            columns=cols,
                            parquet_bytes=parquet_bytes,
                            updated_by="preload",
                        )
                    else:
                        logger.warning(
                            f"[PRELOAD] Skipping DatasetTable '{tname}': name already exists."
                        )

                job = JobRecord(
                    id=str(uuid.uuid4()),
                    job_type="index_doc",
                    idempotency_key=f"index_doc:{doc.id}",
                    target_doc_id=doc.id,
                    requested_by="system",
                    status="queued",
                    payload={"doc_id": doc.id, "filename": filename, "role": role},
                )
                db.add(job)
                db.flush()
                created_jobs.append((job.id, doc.id))
                logger.info(
                    f"[PRELOAD] Registered '{filename}' ({role}) at object_key='{object_key}'"
                )

        db.commit()

    return created_jobs
