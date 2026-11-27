"""
app/core/sql_sandbox.py — Ephemeral :memory: DuckDB SQL sandbox backed by Parquet in Object Storage.
"""

from __future__ import annotations

import threading
from typing import Callable

import duckdb

from app.storage.base import ObjectStorageBackend


def _execute_sandboxed_select(
    sql: str,
    allowed_tables: list[str],
    load_tables_fn: Callable[[duckdb.DuckDBPyConnection, list[str], dict[str, str]], None],
    row_limit: int = 1000,
    dry_run: bool = False,
):
    """
    Shared DuckDB isolated :memory: SQL executor:
    - Extracts and verifies a single SELECT statement
    - Authorizes every referenced physical table
    - Loads only authorized referenced tables into ephemeral :memory:
    - Enforces enable_external_access=False, memory_limit=256MB, threads=2, 10s timeout
    - When dry_run=True, executes EXPLAIN <sql> to verify binding/types/columns without returning data
    """
    sandbox = duckdb.connect(
        ":memory:",
        config={
            "memory_limit": "256MB",
            "threads": 2,
        },
    )
    timer = None
    try:
        statements = sandbox.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Only one SELECT statement is allowed.")
        referenced = sandbox.get_table_names(sql)
        allowed = {name.lower(): name for name in allowed_tables}
        if not referenced or any(name.lower() not in allowed for name in referenced):
            raise ValueError("The query must use only datasets available to your role.")

        load_tables_fn(sandbox, list(referenced), allowed)

        # Lock down external file/network access before running untrusted generated SQL.
        sandbox.execute("SET enable_external_access = false")

        timer = threading.Timer(10, sandbox.interrupt)
        timer.daemon = True
        timer.start()

        if dry_run:
            sandbox.execute(f"EXPLAIN {sql}").fetchall()
            return [], [], list(referenced), False

        cursor = sandbox.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(row_limit + 1)
        return rows[:row_limit], columns, list(referenced), len(rows) > row_limit
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        sandbox.close()


def _load_parquet_tables(
    allowed_tables_map: dict[str, str],
    storage: ObjectStorageBackend,
) -> Callable[[duckdb.DuckDBPyConnection, list[str], dict[str, str]], None]:
    key_lookup = {name.lower(): parquet_key for name, parquet_key in allowed_tables_map.items()}

    def _load(
        sandbox: duckdb.DuckDBPyConnection,
        referenced: list[str],
        allowed: dict[str, str],
    ) -> None:
        for name in referenced:
            canonical = allowed[name.lower()]
            parquet_key = key_lookup[name.lower()]
            quoted = '"' + canonical.replace('"', '""') + '"'
            with storage.open_local_temp(parquet_key, suffix=".parquet") as tmp_parquet:
                escaped_path = str(tmp_parquet).replace("'", "''")
                sandbox.execute(
                    f"CREATE TABLE {quoted} AS SELECT * FROM read_parquet('{escaped_path}')"
                )

    return _load


def dry_run_explain_parquet_tables(
    sql: str,
    allowed_tables_map: dict[str, str],
    storage: ObjectStorageBackend,
) -> list[str]:
    """
    Validate generated SELECT SQL via DuckDB `EXPLAIN` against authorized Parquet schemas
    inside an isolated :memory: sandbox. Returns referenced table names on success.
    """
    _, _, used_tables, _ = _execute_sandboxed_select(
        sql=sql,
        allowed_tables=list(allowed_tables_map.keys()),
        load_tables_fn=_load_parquet_tables(allowed_tables_map, storage),
        dry_run=True,
    )
    return used_tables


def query_authorized_parquet_tables(
    sql: str,
    allowed_tables_map: dict[str, str],
    storage: ObjectStorageBackend,
    row_limit: int = 1000,
):
    """
    Execute a single SELECT query against authorized Parquet datasets stored in
    ObjectStorageBackend. Streams ONLY the referenced authorized tables into an
    isolated :memory: DuckDB session and deletes temporary files immediately.
    """
    return _execute_sandboxed_select(
        sql=sql,
        allowed_tables=list(allowed_tables_map.keys()),
        load_tables_fn=_load_parquet_tables(allowed_tables_map, storage),
        row_limit=row_limit,
    )


def query_authorized_tables(
    database: str,
    sql: str,
    allowed_tables: list[str],
    row_limit: int = 1000,
):
    """Legacy DuckDB-file fixture helper sharing the hardened :memory: sandbox."""

    def _load_from_duckdb(
        sandbox: duckdb.DuckDBPyConnection,
        referenced: list[str],
        allowed: dict[str, str],
    ) -> None:
        source = duckdb.connect(database, read_only=True)
        try:
            for index, name in enumerate(referenced):
                canonical = allowed[name.lower()]
                quoted = '"' + canonical.replace('"', '""') + '"'
                frame = source.execute(f"SELECT * FROM {quoted}").fetchdf()
                registered = f"_authorized_frame_{index}"
                sandbox.register(registered, frame)
                sandbox.execute(f"CREATE TABLE {quoted} AS SELECT * FROM {registered}")
                sandbox.unregister(registered)
        finally:
            source.close()

    return _execute_sandboxed_select(
        sql=sql,
        allowed_tables=allowed_tables,
        load_tables_fn=_load_from_duckdb,
        row_limit=row_limit,
    )
