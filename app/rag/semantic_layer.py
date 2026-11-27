"""
app/rag/semantic_layer.py — Governed semantic models (KPIs, dimensions, synonyms, joins) & chart inference.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
import logging
import math
import re
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import SemanticModel

logger = logging.getLogger("FinSight.semantic")

_NUMERIC_HINTS = (
    "revenue",
    "sales",
    "amount",
    "cost",
    "expense",
    "spend",
    "budget",
    "salary",
    "bonus",
    "profit",
    "margin",
    "ebitda",
    "count",
    "total",
    "rate",
    "score",
    "rating",
    "roi",
    "impressions",
    "clicks",
    "conversions",
    "leads",
    "price",
    "qty",
    "quantity",
)
_TIME_AXIS_HINTS = ("date", "month", "quarter", "year", "week", "day", "period", "fiscal")


def _quote_col(col: str) -> str:
    return f'"{col.replace(chr(34), chr(34) * 2)}"'


def derive_starter_semantic_model(
    table_name: str,
    *,
    columns: list[str] | None = None,
    parquet_bytes: bytes | None = None,
) -> dict[str, Any]:
    """
    Infer canonical dimensions, metrics, and common synonyms from Parquet schema or column names.
    Never overwrites curator/admin edits once persisted.
    """
    typed_cols: list[tuple[str, str]] = []
    if parquet_bytes:
        try:
            schema = pq.read_schema(BytesIO(parquet_bytes))
            for field in schema:
                t = field.type
                if pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_decimal(t):
                    kind = "numeric"
                elif pa.types.is_temporal(t):
                    kind = "temporal"
                else:
                    kind = "text"
                typed_cols.append((str(field.name), kind))
        except Exception as exc:
            logger.debug(f"[Semantic] Parquet schema inspection skipped for {table_name}: {exc}")

    if not typed_cols and columns:
        for col in columns:
            cl = col.lower()
            if any(h in cl for h in _TIME_AXIS_HINTS):
                kind = "temporal"
            elif any(h in cl for h in _NUMERIC_HINTS):
                kind = "numeric"
            else:
                kind = "text"
            typed_cols.append((col, kind))

    metrics: list[dict[str, str]] = []
    dimensions: list[dict[str, str]] = []
    synonyms: dict[str, str] = {}

    for col, kind in typed_cols:
        clean_label = col.replace("_", " ").replace("-", " ").strip()
        if kind == "numeric":
            metrics.append(
                {
                    "name": f"total_{re.sub(r'[^a-zA-Z0-9_]+', '_', col.lower()).strip('_')}",
                    "label": f"Total {clean_label}",
                    "expression": f"SUM(CAST({_quote_col(col)} AS DOUBLE))",
                    "column": col,
                    "description": f"Sum of {clean_label}",
                }
            )
        else:
            dimensions.append(
                {
                    "name": col,
                    "type": kind,
                    "description": f"{clean_label} ({kind})",
                }
            )

        low = col.lower()
        if any(k in low for k in ("full_name", "full-name", "employee_name", "emp_name")):
            synonyms["employee name"] = col
        if any(k in low for k in ("designation", "job_title", "position")):
            synonyms["position"] = col
        if "salary" in low or "compensation" in low:
            synonyms["pay"] = col
        if "department" in low or "dept" in low:
            synonyms["team"] = col

    display_name = table_name.replace("_", " ").strip().title()
    return {
        "table_name": table_name,
        "display_name": display_name,
        "description": f"Governed analytical dataset for {display_name}.",
        "metrics": metrics,
        "dimensions": dimensions,
        "synonyms": synonyms,
        "joins": [],
    }


def ensure_starter_semantic_model_sync(
    db: Session,
    *,
    table_name: str,
    doc_id: int | None,
    columns: list[str] | None = None,
    parquet_bytes: bytes | None = None,
    updated_by: str = "system",
) -> SemanticModel:
    existing = db.scalar(
        select(SemanticModel).where(func.lower(SemanticModel.table_name) == table_name.lower())
    )
    if existing is not None:
        return existing
    starter = derive_starter_semantic_model(
        table_name, columns=columns, parquet_bytes=parquet_bytes
    )
    row = SemanticModel(
        table_name=table_name,
        doc_id=doc_id,
        display_name=starter["display_name"],
        description=starter["description"],
        metrics_json=starter["metrics"],
        dimensions_json=starter["dimensions"],
        synonyms_json=starter["synonyms"],
        joins_json=starter["joins"],
        updated_by=updated_by,
    )
    db.add(row)
    db.flush()
    return row


def format_semantic_context(
    dataset_records: list[dict[str, Any]],
    semantic_models: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render governed table schemas, canonical metrics, synonyms, and join rules for NL2SQL."""
    models_lookup = {k.lower(): v for k, v in (semantic_models or {}).items()}
    blocks: list[str] = []
    for rec in dataset_records:
        tname = rec["table_name"]
        cols = rec.get("columns", [])
        lines = [f"Table: {tname}"]
        model = models_lookup.get(tname.lower())
        if model:
            if model.get("description"):
                lines.append(f"Description: {model['description']}")
            lines.append(f"Columns: {', '.join(cols)}")
            metrics = model.get("metrics") or []
            if metrics:
                metric_strs = [
                    f"{m.get('name')} = {m.get('expression')} ({m.get('description', '')})"
                    for m in metrics[:12]
                    if m.get("name") and m.get("expression")
                ]
                if metric_strs:
                    lines.append("Canonical Metrics: " + "; ".join(metric_strs))
            synonyms = model.get("synonyms") or {}
            if synonyms:
                syn_strs = [f"'{k}' -> {v}" for k, v in list(synonyms.items())[:12]]
                lines.append("Business Synonyms: " + ", ".join(syn_strs))
            joins = model.get("joins") or []
            if joins:
                join_strs = [
                    f"{j.get('target_table')} ON {j.get('condition')}"
                    for j in joins[:6]
                    if j.get("target_table") and j.get("condition")
                ]
                if join_strs:
                    lines.append("Approved Joins: " + "; ".join(join_strs))
        else:
            lines.append(f"Columns: {', '.join(cols)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 4) if abs(value) < 1e9 else value
    if isinstance(value, int):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_scalar(value.item())
        except Exception:
            pass
    return str(value)


def infer_chart_spec(
    columns: list[str],
    rows: list[list[Any] | tuple[Any, ...]],
    *,
    title: str = "Query Results",
    hint: str | None = None,
) -> dict[str, Any]:
    """
    Build a deterministic Recharts-ready `chart_spec` from SQL tabular results.
    Returns `{"type": "none", ...}` cleanly when results are single-row or non-numeric.
    """
    empty = {"type": "none", "title": title, "xKey": "", "yKeys": [], "rows": []}
    if not columns or not rows or len(rows) < 2 or len(columns) < 2:
        return empty

    sample = rows[:50]
    numeric_cols: list[str] = []
    label_cols: list[str] = []

    for col_idx, col_name in enumerate(columns):
        saw_numeric = False
        saw_non_numeric = False
        for row in sample:
            val = row[col_idx] if col_idx < len(row) else None
            if val is None:
                continue
            if isinstance(val, (int, float, Decimal)) and not isinstance(val, bool):
                saw_numeric = True
            else:
                saw_non_numeric = True
        if saw_numeric and not saw_non_numeric:
            numeric_cols.append(col_name)
        else:
            label_cols.append(col_name)

    if not numeric_cols or not label_cols:
        return empty

    x_key = label_cols[0]
    y_keys = numeric_cols[:4]

    chart_type = "bar"
    hint_clean = (hint or "").strip().lower()
    if hint_clean in {"bar", "line", "area", "pie"}:
        chart_type = hint_clean
    elif any(h in x_key.lower() for h in _TIME_AXIS_HINTS):
        chart_type = "line"

    if chart_type == "pie" and (len(sample) > 8 or len(y_keys) > 1):
        chart_type = "bar"

    chart_rows: list[dict[str, Any]] = []
    for row in sample:
        item: dict[str, Any] = {x_key: _json_scalar(row[columns.index(x_key)])}
        for yk in y_keys:
            idx = columns.index(yk)
            item[yk] = _json_scalar(row[idx] if idx < len(row) else None)
        chart_rows.append(item)

    return {
        "type": chart_type,
        "title": title,
        "xKey": x_key,
        "yKeys": y_keys,
        "rows": chart_rows,
    }
