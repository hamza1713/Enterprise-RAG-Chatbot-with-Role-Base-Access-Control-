"""
app/api/semantic.py — Governed NL2SQL semantic model management endpoints (C-Level).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _require_clevel
from app.core.audit import record_audit_event
from app.core.cache import cache_manager
from app.db.models import DatasetTable, SemanticModel
from app.db.session import get_db
from app.rag.semantic_layer import derive_starter_semantic_model

router = APIRouter(tags=["semantic"])


class SemanticModelUpsertRequest(BaseModel):
    display_name: str | None = None
    description: str = ""
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    synonyms: dict[str, str] = Field(default_factory=dict)
    joins: list[dict[str, Any]] = Field(default_factory=list)


def _serialize(model: SemanticModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "table_name": model.table_name,
        "doc_id": model.doc_id,
        "display_name": model.display_name,
        "description": model.description or "",
        "metrics": list(model.metrics_json or []),
        "dimensions": list(model.dimensions_json or []),
        "synonyms": dict(model.synonyms_json or {}),
        "joins": list(model.joins_json or []),
        "updated_by": model.updated_by,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
    }


@router.get("/semantic-models")
async def list_semantic_models(
    _user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    """List all governed semantic models and auto-bootstrap missing DatasetTable definitions."""
    tables = list(await db.scalars(select(DatasetTable).order_by(DatasetTable.table_name.asc())))
    models = list(await db.scalars(select(SemanticModel).order_by(SemanticModel.table_name.asc())))
    by_name = {m.table_name.lower(): m for m in models}

    created_any = False
    for tbl in tables:
        if tbl.table_name.lower() not in by_name:
            starter = derive_starter_semantic_model(
                tbl.table_name, columns=list(tbl.columns_json or [])
            )
            created = SemanticModel(
                table_name=tbl.table_name,
                doc_id=tbl.doc_id,
                display_name=starter["display_name"],
                description=starter["description"],
                metrics_json=starter["metrics"],
                dimensions_json=starter["dimensions"],
                synonyms_json=starter["synonyms"],
                joins_json=starter["joins"],
                updated_by="system",
            )
            db.add(created)
            by_name[tbl.table_name.lower()] = created
            created_any = True

    if created_any:
        await db.commit()
        models = list(
            await db.scalars(select(SemanticModel).order_by(SemanticModel.table_name.asc()))
        )

    return {"models": [_serialize(m) for m in models]}


@router.put("/semantic-models/{table_name}")
async def upsert_semantic_model(
    table_name: str,
    body: SemanticModelUpsertRequest,
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    dataset = await db.scalar(
        select(DatasetTable).where(func.lower(DatasetTable.table_name) == table_name.strip().lower())
    )
    existing = await db.scalar(
        select(SemanticModel).where(func.lower(SemanticModel.table_name) == table_name.strip().lower())
    )
    if existing is None and dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset table '{table_name}' not found.")

    canonical_name = dataset.table_name if dataset is not None else existing.table_name
    display_name = (body.display_name or canonical_name.replace("_", " ").title()).strip()

    if existing is None:
        existing = SemanticModel(
            table_name=canonical_name,
            doc_id=dataset.doc_id if dataset is not None else None,
            display_name=display_name,
            description=body.description.strip(),
            metrics_json=body.metrics,
            dimensions_json=body.dimensions,
            synonyms_json=body.synonyms,
            joins_json=body.joins,
            updated_by=user["username"],
        )
        db.add(existing)
    else:
        existing.display_name = display_name
        existing.description = body.description.strip()
        existing.metrics_json = body.metrics
        existing.dimensions_json = body.dimensions
        existing.synonyms_json = body.synonyms
        existing.joins_json = body.joins
        existing.updated_by = user["username"]

    await db.commit()
    await db.refresh(existing)
    cache_manager.clear()
    await record_audit_event(
        username=user["username"],
        user_role=user["role"],
        auth_provider=user.get("auth_provider", "local"),
        event_type="semantic_model_update",
        authorized_dataset_names=[existing.table_name],
        outcome="allow",
        raw_prompt=f"semantic_upsert:{existing.table_name}",
        ai_disclosure=False,
    )
    return _serialize(existing)


@router.post("/semantic-models/{table_name}/reset")
async def reset_semantic_model(
    table_name: str,
    user: dict = Depends(_require_clevel),
    db: AsyncSession = Depends(get_db),
):
    dataset = await db.scalar(
        select(DatasetTable).where(func.lower(DatasetTable.table_name) == table_name.strip().lower())
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"Dataset table '{table_name}' not found.")

    starter = derive_starter_semantic_model(
        dataset.table_name, columns=list(dataset.columns_json or [])
    )
    existing = await db.scalar(
        select(SemanticModel).where(func.lower(SemanticModel.table_name) == dataset.table_name.lower())
    )
    if existing is None:
        existing = SemanticModel(
            table_name=dataset.table_name,
            doc_id=dataset.doc_id,
            display_name=starter["display_name"],
            description=starter["description"],
            metrics_json=starter["metrics"],
            dimensions_json=starter["dimensions"],
            synonyms_json=starter["synonyms"],
            joins_json=starter["joins"],
            updated_by=user["username"],
        )
        db.add(existing)
    else:
        existing.display_name = starter["display_name"]
        existing.description = starter["description"]
        existing.metrics_json = starter["metrics"]
        existing.dimensions_json = starter["dimensions"]
        existing.synonyms_json = starter["synonyms"]
        existing.joins_json = starter["joins"]
        existing.updated_by = user["username"]

    await db.commit()
    await db.refresh(existing)
    cache_manager.clear()
    await record_audit_event(
        username=user["username"],
        user_role=user["role"],
        auth_provider=user.get("auth_provider", "local"),
        event_type="semantic_model_reset",
        authorized_dataset_names=[existing.table_name],
        outcome="allow",
        raw_prompt=f"semantic_reset:{existing.table_name}",
        ai_disclosure=False,
    )
    return _serialize(existing)
