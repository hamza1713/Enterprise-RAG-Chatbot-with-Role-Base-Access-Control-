"""
app/rag/csv_query.py — Natural-language → SQL → DuckDB pipeline.

Renamed from `app/rag_utils/csv_query.py`.
Updated to import from `app.core.config` instead of the old secret_key module.
"""

import re
import sqlite3
from pathlib import Path

import duckdb
import tabulate
from google import genai

from app.core.config import (
    DB_PATH,
    DUCKDB_PATH,
    google_api_key,
    generate_content_with_fallback,
)

_client = genai.Client(api_key=google_api_key or "DUMMY_KEY")
_DUCKDB_FILE = str(DUCKDB_PATH)


# ── Access control helpers ────────────────────────────────────────────────────

def get_allowed_tables_for_role(role: str) -> list[str]:
    """Return the table names this role is allowed to query in DuckDB."""
    d_conn     = duckdb.connect(_DUCKDB_FILE, read_only=True)
    role_lower = role.lower()
    try:
        if role_lower == "c-level":
            tables   = [r[0] for r in d_conn.execute("SELECT table_name FROM tables_metadata").fetchall()]
            physical = [r[0] for r in d_conn.execute("SHOW TABLES").fetchall()]
            return list(set(tables + physical))
        elif role_lower == "general":
            return [r[0] for r in d_conn.execute(
                "SELECT table_name FROM tables_metadata WHERE LOWER(role) = 'general'"
            ).fetchall()]
        else:
            return [r[0] for r in d_conn.execute(
                "SELECT table_name FROM tables_metadata "
                "WHERE LOWER(role) = ? OR LOWER(role) = 'general'",
                [role_lower],
            ).fetchall()]
    except Exception as exc:
        print(f"[DuckDB] get_allowed_tables_for_role error: {exc}")
        return []
    finally:
        d_conn.close()


def extract_tables_from_sql(sql: str) -> list[str]:
    return re.findall(
        r'(?:FROM|JOIN)\s+["`\'\\[]?([a-zA-Z0-9_]+)["`\'\\]]?',
        sql, flags=re.IGNORECASE,
    )


_FORBIDDEN_KEYWORDS = {"insert", "update", "delete", "drop", "alter", "create"}


def is_safe_query(sql: str) -> bool:
    lowered = sql.strip().lower().rstrip(";")
    return lowered.startswith("select") and all(
        kw not in lowered for kw in _FORBIDDEN_KEYWORDS
    )


# ── NL → SQL translation ──────────────────────────────────────────────────────

def translate_nl_to_sql(question: str, allowed_tables: list[str]) -> str:
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    rows = conn.execute(
        "SELECT filename, headers_str FROM documents WHERE headers_str IS NOT NULL"
    ).fetchall()
    conn.close()

    allowed_lower = {t.lower() for t in allowed_tables}
    schemas: list[str] = []
    for filename, headers_str in rows:
        tname = re.sub(r"[^a-zA-Z0-9_]", "_", Path(filename).stem)
        if tname.lower() in allowed_lower:
            cols = ", ".join(headers_str.split(","))
            schemas.append(f"Table: {tname}\nColumns: {cols}")

    schema_block = "\n\n".join(schemas)

    prompt = f"""
    You are an assistant that converts natural language questions into safe SQL SELECT queries.

    Use only the following schemas:
    {schema_block}

    Constraints:
    - Use only the tables listed above.
    - Use the exact column names as-is (including hyphens, underscores, casing).
    - If column names contain spaces or special characters, wrap them in double quotes.
    - When performing mathematical calculations or additions (e.g., `+`, `SUM`, `AVG`) on numeric fields that could be stored as text/VARCHAR (such as formatted numbers, empty strings, or text columns), use explicit casting: `CAST(column AS DOUBLE)`. For example, write `CAST("Social Media" AS DOUBLE)` instead of adding it directly, to prevent DuckDB Binder Errors.
    - Support filters such as greater than (>), less than (<), equals (=), and wildcard text matching (LIKE with %).
    - When filtering text values, use case-insensitive matching if appropriate (e.g. LOWER(column) LIKE '%value%').
    - Return only a SELECT query (no INSERT/UPDATE/DELETE).
    - If asked about 'employee name', consider alternatives like 'full-name', 'last-name'.
    - If asked about 'position', consider synonyms like 'role', 'designation'.
    - Do not mix aggregate functions (like COUNT(*)) with *. Use either a grouped summary or return them separately."
    Natural Language Question: "{question}"

    SQL:
    """

    try:
        response_text = generate_content_with_fallback(_client, prompt)
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            response_text = response_text.strip("`").strip()
            if response_text.lower().startswith("sql\n"):
                response_text = response_text[4:].strip()
            elif response_text.lower().startswith("sql "):
                response_text = response_text[4:].strip()
        return response_text
    except Exception as exc:
        print(f"[CSV_QUERY] LLM call failed: {exc}")
        return "Error generating SQL"


def get_filename_for_table(table_name: str) -> str:
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    rows = conn.execute(
        "SELECT filename FROM documents WHERE headers_str IS NOT NULL"
    ).fetchall()
    conn.close()
    for (filename,) in rows:
        stem = re.sub(r"[^a-zA-Z0-9_]", "_", Path(filename).stem)
        if stem.lower() == table_name.lower():
            return filename
    return table_name + ".csv"


# ── Public entry point ────────────────────────────────────────────────────────

async def ask_csv(
    question: str,
    role: str,
    username: str,
    return_sql: bool = False,
) -> dict:
    allowed_tables       = get_allowed_tables_for_role(role)
    allowed_tables_lower = {t.lower() for t in allowed_tables}

    try:
        sql = translate_nl_to_sql(question, allowed_tables)

        if not is_safe_query(sql):
            return {"answer": "Only SELECT queries are allowed.", "error": True, "type": "technical"}

        referenced_tables = extract_tables_from_sql(sql)

        # Identify physical tables in DuckDB for fallback detection
        d_tmp = duckdb.connect(_DUCKDB_FILE, read_only=True)
        try:
            all_registered = [r[0].lower() for r in d_tmp.execute(
                "SELECT table_name FROM tables_metadata"
            ).fetchall()]
        except Exception:
            all_registered = []
        finally:
            d_tmp.close()

        role_lower = role.lower()
        for table in referenced_tables:
            if not re.match(r"^[a-zA-Z0-9_]+$", table):
                return {
                    "answer": f"Security restriction: Table name '{table}' is malformed.",
                    "error": True, "type": "security",
                }
            tl = table.lower()
            if tl not in all_registered:
                return {
                    "answer": f"Table '{table}' does not exist in structured data.",
                    "error": True, "type": "technical",
                }
            if role_lower != "c-level" and tl not in allowed_tables_lower:
                return {
                    "answer": f"Access denied: You do not have permissions to access table '{table}'.",
                    "error": True, "type": "security",
                }

        d_conn = duckdb.connect(_DUCKDB_FILE, read_only=True)
        try:
            result  = d_conn.execute(sql).fetchall()
            columns = [desc[0] for desc in d_conn.description]
        finally:
            d_conn.close()

        output     = [list(row) for row in result]
        total_rows = len(output)

        if total_rows > 10:
            display_output = output[:10]
            note = (
                f"\n\n*(Showing top 10 of {total_rows} rows. "
                f"To view the complete dataset, click the Reference drawer below "
                f"or use the Document Explorer tab.)*"
            )
        else:
            display_output = output
            note           = ""

        md_table = tabulate.tabulate(display_output, headers=columns, tablefmt="github") + note
        sources  = list({get_filename_for_table(t) for t in referenced_tables})

        response = {
            "answer":  md_table if output else "Query executed, but no results found.",
            "sources": sources,
        }
        if return_sql:
            response["sql"] = sql

        return response

    except Exception as exc:
        return {"answer": f"❌ Error: {exc}", "error": True, "type": "technical"}
