"""
app/core/database.py — SQLite & DuckDB setup helpers.

Extracted from the old monolithic `app/main.py`.
All schema creation and connection helpers live here so they are
lazily invoked (not at import time) and testable in isolation.

Fix (2026-06-28): Added `heal_stale_filepaths()` which is called on
every startup to correct any DB records whose `filepath` column still
points to a previous project directory (e.g. after renaming/moving
the project folder).
"""

import sqlite3
import logging
import os
import re
from pathlib import Path

import duckdb
import pandas as pd

from .config import DB_PATH, DUCKDB_DIR, DUCKDB_PATH, RESOURCES_DIR, UPLOAD_DIR

logger = logging.getLogger("FinSight.db")

# ── Ensure directories exist ───────────────────────────────────────────────────
DUCKDB_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SQLite helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_db_conn() -> sqlite3.Connection:
    """Return a WAL-mode SQLite connection to the main application DB."""
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_sqlite_schema() -> None:
    """Create tables if they don't exist (idempotent)."""
    conn = get_db_conn()
    conn.cursor().executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role     TEXT
        );
        CREATE TABLE IF NOT EXISTS roles (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS documents (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            filename         TEXT,
            role             TEXT,
            filepath         TEXT NOT NULL,
            headers_str      TEXT,
            embedded         INTEGER DEFAULT 0,
            total_chunks     INTEGER DEFAULT 0,
            embedded_chunks  INTEGER DEFAULT 0
        );
    """)
    conn.commit()

    # Safely add columns that may not exist in older DB files
    for col in ["total_chunks", "embedded_chunks"]:
        try:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Path-healing (self-correcting on project rename / move)
# ══════════════════════════════════════════════════════════════════════════════

def heal_stale_filepaths() -> None:
    """
    Detect and fix any `filepath` values in the `documents` table that do NOT
    point at the current project root (BASE_DIR).

    Two cases handled:
      1. Absolute paths from a previous project directory  e.g. Finsight_02 → Finsight_05
      2. Relative paths (no drive letter)  e.g. 'static/uploads/…' → absolute

    Safe to call on every startup — only updates rows that need fixing.
    """
    current_upload_root = str(UPLOAD_DIR.parent.parent)  # …/Finsight_05

    conn = get_db_conn()
    c    = conn.cursor()
    rows = c.execute("SELECT id, filepath FROM documents").fetchall()

    changed = 0
    for row_id, fp in rows:
        # ── Case 1: absolute path pointing somewhere OTHER than current root ──
        if os.path.isabs(fp):
            if not fp.startswith(current_upload_root):
                # Derive the sub-path after 'static/uploads/…'
                try:
                    idx     = fp.lower().index("static")
                    rel     = fp[idx:]          # e.g. 'static\\uploads\\General\\file.md'
                    new_fp  = os.path.normpath(os.path.join(current_upload_root, rel))
                    c.execute("UPDATE documents SET filepath=? WHERE id=?", (new_fp, row_id))
                    logger.info(f"[HealPaths] Fixed absolute: {fp!r} → {new_fp!r}")
                    changed += 1
                except ValueError:
                    logger.warning(f"[HealPaths] Cannot heal path (no 'static' segment): {fp!r}")

        # ── Case 2: relative path ─────────────────────────────────────────────
        else:
            new_fp = os.path.normpath(os.path.join(current_upload_root, fp))
            c.execute("UPDATE documents SET filepath=? WHERE id=?", (new_fp, row_id))
            logger.info(f"[HealPaths] Fixed relative: {fp!r} → {new_fp!r}")
            changed += 1

    if changed:
        conn.commit()
        logger.info(f"[HealPaths] {changed} filepath(s) corrected.")
    else:
        logger.debug("[HealPaths] All filepaths are current — no changes needed.")

    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  DuckDB helpers
# ══════════════════════════════════════════════════════════════════════════════

def init_duckdb_schema() -> None:
    """Create the DuckDB tables_metadata table if it doesn't exist."""
    dc = duckdb.connect(str(DUCKDB_PATH))
    dc.execute("""
        CREATE TABLE IF NOT EXISTS tables_metadata (
            table_name TEXT,
            role       TEXT
        )
    """)
    dc.close()


def reconcile_duckdb_from_sqlite() -> None:
    """
    Ensure every CSV registered in SQLite has a matching DuckDB table.
    Safe to call on every startup — skips files already present.
    """
    conn = get_db_conn()
    rows = conn.execute(
        "SELECT filename, role, filepath, headers_str FROM documents "
        "WHERE headers_str IS NOT NULL"
    ).fetchall()
    conn.close()

    if not rows:
        return

    try:
        dc = duckdb.connect(str(DUCKDB_PATH))
        registered = {r[0].lower() for r in dc.execute("SELECT table_name FROM tables_metadata").fetchall()}
        physical   = {r[0].lower() for r in dc.execute("SHOW TABLES").fetchall()}
    except Exception as exc:
        logger.error(f"[RECONCILE] DuckDB open error: {exc}")
        return

    for filename, role, filepath, _headers_str in rows:
        tname = re.sub(r"[^a-zA-Z0-9_]", "_", Path(filepath).stem)
        if tname.lower() in registered and tname.lower() in physical:
            continue
        try:
            df = pd.read_csv(filepath)
            dc.execute("DELETE FROM tables_metadata WHERE table_name = ?", (tname,))
            dc.register("_df_rec", df)
            dc.execute(f"CREATE OR REPLACE TABLE {tname} AS SELECT * FROM _df_rec")
            dc.execute(
                "INSERT INTO tables_metadata (table_name, role) VALUES (?, ?)",
                (tname, role),
            )
            dc.unregister("_df_rec")
            logger.info(f"[RECONCILE] Loaded missing table '{tname}' (role={role})")
        except Exception as exc:
            logger.error(f"[RECONCILE] Failed for '{tname}': {exc}")

    dc.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Default data seed
# ══════════════════════════════════════════════════════════════════════════════

_ROLE_MAPPING: dict[str, str] = {
    "engineering": "Engineering",
    "finance":     "Finance",
    "general":     "General",
    "hr":          "HR",
    "marketing":   "Marketing",
}


def preload_default_data() -> None:
    """
    Copy documents from resources/data/<dept>/ into static/uploads/<role>/,
    register them in SQLite with ABSOLUTE filepaths, and load CSVs into DuckDB.
    Runs in a background thread on startup — idempotent.
    """
    if not RESOURCES_DIR.exists():
        reconcile_duckdb_from_sqlite()
        return

    conn = get_db_conn()
    c    = conn.cursor()

    # Ensure all known roles exist
    for role_name in _ROLE_MAPPING.values():
        c.execute("INSERT OR IGNORE INTO roles (role_name) VALUES (?)", (role_name,))
    conn.commit()

    import shutil

    for sub in RESOURCES_DIR.iterdir():
        if not sub.is_dir():
            continue
        role = _ROLE_MAPPING.get(sub.name.lower(), sub.name.capitalize())

        for filepath in sub.iterdir():
            if not filepath.is_file():
                continue

            filename  = filepath.name
            extension = filepath.suffix.lower()

            c.execute(
                "SELECT id FROM documents WHERE filename=? AND role=?",
                (filename, role),
            )
            if c.fetchone():
                continue  # already registered

            dest_dir  = UPLOAD_DIR / role
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / filename
            shutil.copy2(filepath, dest_path)

            # Always store the resolved absolute path
            dest_abs  = str(dest_path.resolve())

            headers_str: str | None = None
            if extension == ".csv":
                try:
                    df     = pd.read_csv(dest_path)
                    tname  = re.sub(r"[^a-zA-Z0-9_]", "_", dest_path.stem)
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
                except Exception as exc:
                    logger.error(f"[PRELOAD] DuckDB error for {filename}: {exc}")

            c.execute(
                "INSERT INTO documents (filename, role, filepath, headers_str, embedded) "
                "VALUES (?,?,?,?,0)",
                (filename, role, dest_abs, headers_str),
            )
            conn.commit()
            logger.info(f"[PRELOAD] Registered {filename} ({role}) at {dest_abs}")

    conn.close()
    reconcile_duckdb_from_sqlite()

    # Trigger RAG indexer after seeding
    try:
        from app.rag.module import run_indexer
        run_indexer()
        logger.info("[PRELOAD] Indexer triggered.")
    except Exception as exc:
        logger.warning(f"[PRELOAD] Indexer warning: {exc}")
