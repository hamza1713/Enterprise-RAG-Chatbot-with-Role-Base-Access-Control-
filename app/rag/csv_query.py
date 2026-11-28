"""
app/rag/csv_query.py — Governed Semantic NL2SQL → sqlglot AST → DuckDB EXPLAIN dry-run →
bounded self-correction → Ephemeral :memory: Parquet sandbox + chart inference.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp
import tabulate
from sqlalchemy import func, select

from app.authz.openfga import get_rebac_service
from app.core.config import (
    GEMINI_CHAT_MODEL,
    SQL_MAX_RETRIES,
    generate_content_with_fallback,
    generate_structured_with_fallback,
    get_genai_client,
)
from app.core.sql_sandbox import (
    dry_run_explain_parquet_tables,
    query_authorized_parquet_tables,
)
from app.db.models import DatasetTable, DocumentRecord, SemanticModel
from app.db.session import sync_session
from app.rag.semantic_layer import (
    format_semantic_context,
    infer_chart_spec,
)
from app.storage import get_storage_backend

logger = logging.getLogger("FinSight.csv_query")


# ── Access control & semantic loading helpers ─────────────────────────────────


def get_allowed_dataset_records(
    role: str,
    username: str | None = None,
) -> list[dict]:
    """
    Return allowed DatasetTable records ({doc_id, table_name, parquet_key, columns, role, filename}).
    Uses ReBAC (OpenFGA / Postgres `acl_tuples`) when `username` is provided.
    """
    if username and username.strip():
        return get_rebac_service().list_authorized_datasets_sync(
            username=username.strip(),
            user_role=role,
        )

    role_lower = (role or "general").strip().lower()
    with sync_session() as db:
        stmt = (
            select(
                DatasetTable.doc_id,
                DatasetTable.table_name,
                DatasetTable.parquet_key,
                DatasetTable.columns_json,
                DatasetTable.role,
                DocumentRecord.filename,
            )
            .join(DocumentRecord, DatasetTable.doc_id == DocumentRecord.id)
        )
        if role_lower == "c-level":
            pass
        elif role_lower == "general":
            stmt = stmt.where(func.lower(DatasetTable.role) == "general")
        else:
            stmt = stmt.where(
                (func.lower(DatasetTable.role) == role_lower)
                | (func.lower(DatasetTable.role) == "general")
            )
        rows = db.execute(stmt).all()
        return [
            {
                "doc_id": int(row[0]),
                "table_name": row[1],
                "parquet_key": row[2],
                "columns": list(row[3] or []),
                "role": row[4],
                "filename": row[5],
            }
            for row in rows
        ]


def get_allowed_tables_for_role(role: str, username: str | None = None) -> list[str]:
    """Return the table names this principal is allowed to query."""
    return [item["table_name"] for item in get_allowed_dataset_records(role, username=username)]


def _load_semantic_models_sync(table_names: list[str]) -> dict[str, dict[str, Any]]:
    if not table_names:
        return {}
    names_lower = [t.strip().lower() for t in table_names]
    try:
        with sync_session() as db:
            rows = list(
                db.scalars(
                    select(SemanticModel).where(
                        func.lower(SemanticModel.table_name).in_(names_lower)
                    )
                )
            )
            return {
                r.table_name: {
                    "display_name": r.display_name,
                    "description": r.description,
                    "metrics": list(r.metrics_json or []),
                    "dimensions": list(r.dimensions_json or []),
                    "synonyms": dict(r.synonyms_json or {}),
                    "joins": list(r.joins_json or []),
                }
                for r in rows
            }
    except Exception as exc:
        logger.debug(f"[CSV_QUERY] Semantic model lookup skipped: {exc}")
        return {}


def _get_all_registered_table_names() -> set[str]:
    with sync_session() as db:
        rows = db.scalars(select(DatasetTable.table_name)).all()
        return {name.lower() for name in rows}


_DISALLOWED_AST_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.Copy,
    exp.Attach,
    exp.Detach,
    exp.Pragma,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)
_ALLOWED_ROOT_AST_NODES = (
    exp.Select,
    exp.Union,
    exp.Subquery,
    exp.Intersect,
    exp.Except,
)
_DISALLOWED_TABLE_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "parquet_scan",
    "read_json",
    "read_json_auto",
    "read_text",
    "read_blob",
    "glob",
    "sqlite_scan",
    "postgres_scan",
    "mysql_scan",
    "iceberg_scan",
    "http_get",
    "duckdb_tables",
    "duckdb_columns",
    "duckdb_settings",
    "duckdb_secrets",
    "getenv",
}


def extract_tables_from_sql(sql: str) -> list[str]:
    """Extract physical table names referenced in SQL, excluding CTE aliases."""
    try:
        trees = sqlglot.parse(sql, read="duckdb")
        if len(trees) == 1 and trees[0] is not None:
            tree = trees[0]
            cte_names = {
                cte.alias_or_name.lower()
                for cte in tree.find_all(exp.CTE)
                if cte.alias_or_name
            }
            seen: set[str] = set()
            tables: list[str] = []
            for tbl in tree.find_all(exp.Table):
                name = tbl.name
                if name and name.lower() not in cte_names and name.lower() not in seen:
                    seen.add(name.lower())
                    tables.append(name)
            return tables
    except Exception:
        pass
    return re.findall(
        r'(?:FROM|JOIN)\s+["`\'\\[]?([a-zA-Z0-9_]+)["`\'\\]]?',
        sql,
        flags=re.IGNORECASE,
    )


def is_safe_query(sql: str) -> bool:
    """Validate via DuckDB AST that SQL is a single read-only query without DML/DDL/file functions."""
    if not sql or not sql.strip():
        return False
    try:
        trees = sqlglot.parse(sql, read="duckdb")
    except Exception:
        return False
    if len(trees) != 1 or trees[0] is None:
        return False
    tree = trees[0]
    if not isinstance(tree, _ALLOWED_ROOT_AST_NODES):
        return False
    if any(tree.find_all(*_DISALLOWED_AST_NODES)):
        return False
    for fn in tree.find_all(exp.Anonymous, exp.Func):
        fn_name = (
            fn.name
            if isinstance(fn, exp.Anonymous)
            else (fn.sql_name() or type(fn).__name__)
        ).lower()
        if (
            fn_name.startswith("read_")
            or (fn_name.startswith("read") and isinstance(fn, getattr(exp, "ReadCSV", ())))
            or fn_name in _DISALLOWED_TABLE_FUNCTIONS
        ):
            return False
    return True


def _strip_sql_markdown(text_out: str) -> str:
    cleaned = (text_out or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("sql\n"):
            cleaned = cleaned[4:].strip()
        elif cleaned.lower().startswith("sql "):
            cleaned = cleaned[4:].strip()
    return cleaned


def _build_nl2sql_prompt(
    question: str,
    schema_block: str,
    *,
    previous_sql: str | None = None,
    error_feedback: str | None = None,
) -> str:
    repair_section = ""
    if previous_sql and error_feedback:
        repair_section = f"""
Previous attempt failed DuckDB validation:
Failed SQL:
{previous_sql}

Exact Error:
{error_feedback}

Fix the SQL syntax, column name casing/quoting, numeric CASTs, or GROUP BY clauses so DuckDB executes cleanly.
"""
    return f"""
You are a senior DuckDB SQL analyst converting natural language business questions into safe, single read-only SQL SELECT queries.

Governed Schemas & Semantic Definitions:
{schema_block}

Constraints:
- Use ONLY the tables listed above.
- Preserve exact column names verbatim; wrap columns containing spaces, hyphens, or special characters in double quotes.
- When aggregating/computing math (+, SUM, AVG, /) on numeric columns that could be VARCHAR, use TRY_CAST(column AS DOUBLE) or CAST(column AS DOUBLE) and NULLIF(denominator, 0) to prevent division/binder errors.
- Use case-insensitive matching for text filters (e.g. LOWER(column) LIKE '%value%').
- Return ONLY a single SELECT query (or WITH ... SELECT). Never emit DDL/DML, PRAGMA, COPY, or file-reading functions.
- Prefer canonical metrics and business synonyms listed in the semantic layer above when present.
- Limit unaggregated detail listings cleanly (e.g., LIMIT 200) while keeping totals/group-bys complete.
{repair_section}
Natural Language Question: "{question}"
"""


# ── NL → SQL translation ──────────────────────────────────────────────────────


_DEFAULT_GENERATE_CONTENT = generate_content_with_fallback


def translate_nl_to_sql(
    question: str,
    allowed_tables: list[str],
    dataset_records: list[dict] | None = None,
    semantic_models: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Translate natural language into DuckDB SQL (backwards-compatible text helper)."""
    records = dataset_records if dataset_records is not None else []
    if not records and allowed_tables:
        with sync_session() as db:
            allowed_lower = {t.lower() for t in allowed_tables}
            rows = db.execute(
                select(DatasetTable.table_name, DatasetTable.columns_json)
            ).all()
            records = [
                {"table_name": r[0], "columns": list(r[1] or [])}
                for r in rows
                if r[0].lower() in allowed_lower
            ]
    sem = (
        semantic_models
        if semantic_models is not None
        else _load_semantic_models_sync([r["table_name"] for r in records])
    )
    schema_block = format_semantic_context(records, sem)
    prompt = _build_nl2sql_prompt(question, schema_block) + "\nSQL:\n"

    try:
        response_text = generate_content_with_fallback(get_genai_client(), prompt)
        return _strip_sql_markdown(response_text)
    except Exception as exc:
        logger.warning(f"[CSV_QUERY] LLM call failed: {exc}")
        return "Error generating SQL"


def _generate_sql_plan_step(
    question: str,
    schema_block: str,
    allowed_tables: list[str],
    records: list[dict],
    semantic_models: dict[str, dict[str, Any]],
    *,
    previous_sql: str | None = None,
    error_feedback: str | None = None,
) -> tuple[str, str, str]:
    """
    Generate structured `(sql, chart_hint, title)` using Gemini JSON structured output
    with clean fallback if a caller monkeypatches `generate_content_with_fallback` or
    `translate_nl_to_sql`.
    """
    from app.agents.schemas import SqlPlanOutput

    if previous_sql is None and generate_content_with_fallback is not _DEFAULT_GENERATE_CONTENT:
        sql = translate_nl_to_sql(
            question,
            allowed_tables,
            dataset_records=records,
            semantic_models=semantic_models,
        )
        return sql, "none", "Query Results"

    prompt = _build_nl2sql_prompt(
        question,
        schema_block,
        previous_sql=previous_sql,
        error_feedback=error_feedback,
    )
    try:
        plan = generate_structured_with_fallback(
            get_genai_client(),
            prompt,
            SqlPlanOutput,
            preferred_model=GEMINI_CHAT_MODEL,
        )
        return _strip_sql_markdown(plan.sql), plan.chart_hint, (plan.title or "Query Results").strip()
    except Exception as exc:
        if generate_content_with_fallback is not _DEFAULT_GENERATE_CONTENT or previous_sql is not None:
            raw = generate_content_with_fallback(
                get_genai_client(), prompt + "\nSQL:\n", preferred_model=GEMINI_CHAT_MODEL
            )
            return _strip_sql_markdown(raw), "none", "Query Results"
        logger.debug(f"[CSV_QUERY] Structured SQL fallback ({type(exc).__name__}): retrying plain")
        raw = generate_content_with_fallback(
            get_genai_client(), prompt + "\nSQL:\n", preferred_model=GEMINI_CHAT_MODEL
        )
        return _strip_sql_markdown(raw), "none", "Query Results"


def get_filename_for_table(table_name: str) -> str:
    with sync_session() as db:
        row = db.scalar(
            select(DocumentRecord.filename)
            .join(DatasetTable, DatasetTable.doc_id == DocumentRecord.id)
            .where(func.lower(DatasetTable.table_name) == table_name.lower())
        )
        return row or f"{table_name}.csv"


# ── Governed Execution + EXPLAIN Dry-Run + Self-Correction Entry Point ────────


def _ask_csv_sync(
    question: str,
    role: str,
    username: str,
    return_sql: bool = False,
    *,
    allowed_records_override: list[dict] | None = None,
    max_retries: int | None = None,
) -> dict:
    allowed_records = (
        allowed_records_override
        if allowed_records_override is not None
        else get_allowed_dataset_records(role, username=username)
    )
    if not allowed_records:
        return {
            "answer": "You do not have access to any structured datasets matching this query.",
            "sources": [],
            "sql": None,
            "sql_retries": 0,
            "chart_spec": None,
        }

    allowed_tables_map = {rec["table_name"]: rec["parquet_key"] for rec in allowed_records}
    filename_map = {rec["table_name"].lower(): rec["filename"] for rec in allowed_records}
    allowed_tables = list(allowed_tables_map.keys())
    allowed_tables_lower = {t.lower() for t in allowed_tables}
    semantic_models = _load_semantic_models_sync(allowed_tables)
    schema_block = format_semantic_context(allowed_records, semantic_models)
    all_registered = _get_all_registered_table_names()

    retries_allowed = SQL_MAX_RETRIES if max_retries is None else max(0, int(max_retries))
    storage = get_storage_backend()

    sql = ""
    chart_hint = "none"
    chart_title = "Query Results"
    last_error_msg: str | None = None
    attempts_used = 0

    for attempt in range(retries_allowed + 1):
        attempts_used = attempt + 1
        try:
            if attempt == 0 and translate_nl_to_sql is not _DEFAULT_TRANSLATE_NL_TO_SQL:
                sql = translate_nl_to_sql(question, allowed_tables, dataset_records=allowed_records)
            else:
                sql, chart_hint, chart_title = _generate_sql_plan_step(
                    question,
                    schema_block,
                    allowed_tables,
                    allowed_records,
                    semantic_models,
                    previous_sql=sql if attempt > 0 else None,
                    error_feedback=last_error_msg if attempt > 0 else None,
                )
        except Exception as exc:
            last_error_msg = str(exc)
            break

        if not is_safe_query(sql):
            if sql == "Error generating SQL":
                last_error_msg = "Failed to generate SQL"
                continue
            return {"answer": "Only SELECT queries are allowed.", "error": True, "type": "technical"}

        referenced_tables = extract_tables_from_sql(sql)
        role_lower = (role or "general").lower()
        blocked_security = None
        for table in referenced_tables:
            if not re.match(r"^[a-zA-Z0-9_]+$", table):
                return {
                    "answer": f"Security restriction: Table name '{table}' is malformed.",
                    "error": True,
                    "type": "security",
                }
            tl = table.lower()
            if tl not in all_registered:
                last_error_msg = f"Table '{table}' does not exist in allowed datasets: {allowed_tables}."
                blocked_security = ("technical", f"Table '{table}' does not exist in structured data.")
                break
            if role_lower != "c-level" and tl not in allowed_tables_lower:
                return {
                    "answer": f"Access denied: You do not have permissions to access table '{table}'.",
                    "error": True,
                    "type": "security",
                }

        if blocked_security is not None:
            if attempt < retries_allowed:
                continue
            return {"answer": blocked_security[1], "error": True, "type": blocked_security[0]}

        try:
            dry_run_explain_parquet_tables(
                sql=sql,
                allowed_tables_map=allowed_tables_map,
                storage=storage,
            )
            result, columns, used_tables, truncated = query_authorized_parquet_tables(
                sql=sql,
                allowed_tables_map=allowed_tables_map,
                storage=storage,
            )
            output = [list(row) for row in result]
            total_rows = len(output)

            if total_rows > 10:
                display_output = output[:10]
                note = (
                    f"\n\n*(Showing top 10 of {'at least ' if truncated else ''}{total_rows} rows. "
                    f"To view the complete dataset, click the Reference drawer below "
                    f"or use the Document Explorer tab.)*"
                )
            else:
                display_output = output
                note = ""

            md_table = tabulate.tabulate(display_output, headers=columns, tablefmt="github") + note
            sources = list({
                filename_map.get(t.lower()) or get_filename_for_table(t)
                for t in used_tables
            })
            chart_spec = infer_chart_spec(
                columns,
                output,
                title=chart_title,
                hint=chart_hint if chart_hint != "none" else None,
            )

            response: dict[str, Any] = {
                "answer": md_table if output else "Query executed, but no results found.",
                "sources": sources,
                "sql_retries": max(0, attempts_used - 1),
                "chart_spec": chart_spec if chart_spec.get("type") != "none" else None,
                "columns": columns,
                "row_count": total_rows,
            }
            if return_sql:
                response["sql"] = sql
            return response

        except Exception as exc:
            last_error_msg = str(exc)
            logger.info(
                f"[CSV_QUERY] DuckDB validation/execution error (attempt {attempt + 1}/{retries_allowed + 1}): {exc}"
            )
            if attempt < retries_allowed:
                continue
            return {
                "answer": f"❌ Error: {last_error_msg}",
                "error": True,
                "type": "technical",
                "sql": sql if return_sql else None,
                "sql_retries": max(0, attempts_used - 1),
            }

    return {
        "answer": f"❌ Error: {last_error_msg or 'Unable to generate valid SQL.'}",
        "error": True,
        "type": "technical",
        "sql_retries": max(0, attempts_used - 1),
    }


_DEFAULT_TRANSLATE_NL_TO_SQL = translate_nl_to_sql


async def ask_csv(
    question: str,
    role: str,
    username: str,
    return_sql: bool = False,
    *,
    allowed_records_override: list[dict] | None = None,
    max_retries: int | None = None,
) -> dict:
    return await asyncio.to_thread(
        _ask_csv_sync,
        question,
        role,
        username,
        return_sql,
        allowed_records_override=allowed_records_override,
        max_retries=max_retries,
    )
