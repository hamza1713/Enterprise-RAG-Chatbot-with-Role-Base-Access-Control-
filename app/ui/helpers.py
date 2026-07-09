"""
app/ui/helpers.py — Shared UI helper functions.

Extracted from the old monolithic `app/ui.py`:
  - display_paginated_df  — paginated HTML table widget
  - show_pdf_preview      — inline PDF / text-extraction preview
  - render_message_sources — source document expanders in chat
  - fetch_roles / fetch_bulk_status / fetch_system_metrics — API helpers
  - get_user_documents    — SQLite query for visible docs
"""

import os
import base64
import sqlite3

import pandas as pd
import requests
import streamlit as st

from app.ui.constants import API_URL, DB_PATH, BASE_DIR


# ── Shared API header helper ──────────────────────────────────────────────────
def api_headers() -> dict:
    if "token" in st.session_state:
        return {"Authorization": f"Bearer {st.session_state['token']}"}
    return {}


# ── Paginated dataframe display ───────────────────────────────────────────────
def display_paginated_df(df: pd.DataFrame, key_prefix: str, total_original_rows=None, max_height: int = 420) -> None:
    if len(df) == 0:
        st.info("No data matching the current filters.")
        return

    ctrl1, ctrl2, ctrl3 = st.columns([1.5, 2.5, 2])
    with ctrl1:
        page_size = st.selectbox(
            "Rows/page", [10, 25, 50, 100, 250, 500],
            index=1, key=f"{key_prefix}_ps", label_visibility="collapsed",
        )
    total_pages = max(1, (len(df) - 1) // page_size + 1)
    with ctrl2:
        page_num = (
            st.number_input(
                f"Page (1–{total_pages})", min_value=1,
                max_value=total_pages, value=1, step=1,
                key=f"{key_prefix}_pg", label_visibility="collapsed",
            ) if total_pages > 1 else 1
        )
    with ctrl3:
        st.markdown(
            f'<div style="text-align:right;color:var(--text-muted);font-size:11.5px;padding-top:9px;">'
            f'Page <b style="color:var(--text-secondary)">{page_num}</b>'
            f' of <b style="color:var(--text-secondary)">{total_pages}</b></div>',
            unsafe_allow_html=True,
        )

    start = (page_num - 1) * page_size
    end   = min(start + page_size, len(df))
    html  = df.iloc[start:end].to_html(index=False, escape=True, border=0)
    st.markdown(
        f'<div class="fs-table-wrap" style="max-height:{max_height}px;">{html}</div>'
        f'<div class="fs-table-info">'
        f'<span>Rows <b style="color:var(--text-secondary)">{start+1}–{end}</b>'
        f' of <b style="color:var(--text-secondary)">{len(df)}</b></span>'
        f'<span>{"Total: <b style=\"color:var(--text-secondary)\">"+str(total_original_rows)+"</b> &nbsp;·&nbsp; " if total_original_rows else ""}'
        f'Columns: <b style="color:var(--text-secondary)">{len(df.columns)}</b></span></div>',
        unsafe_allow_html=True,
    )


# ── PDF preview ───────────────────────────────────────────────────────────────
def show_pdf_preview(filepath: str, source_name: str, key_suffix: str = "") -> None:
    import pdfplumber
    import urllib.parse
    preview_mode = st.radio(
        "Preview mode", ["📄 Rendered PDF", "📝 Extracted text"],
        horizontal=True, key=f"pdf_preview_{source_name}_{key_suffix}", label_visibility="collapsed",
    )
    if preview_mode == "📄 Rendered PDF":
        try:
            token = st.session_state.get("token", "")
            encoded_path = urllib.parse.quote(filepath)
            pdf_url = f"{API_URL}/preview-pdf?filepath={encoded_path}&token={token}"
            st.markdown(
                f'<iframe src="{pdf_url}" '
                f'width="100%" height="600px" style="border:1px solid var(--border); border-radius: 8px;" '
                f'type="application/pdf"></iframe>',
                unsafe_allow_html=True,
            )
        except Exception:
            st.info("Inline rendering unavailable. Switch to Extracted text mode.")
    else:
        try:
            with pdfplumber.open(filepath) as pdf:
                total_pages = len(pdf.pages)
                if total_pages == 0:
                    st.info("No pages found in this PDF.")
                    return
                
                # Page key to keep track of state
                page_key = f"pdf_page_{source_name}_{key_suffix}"
                if page_key not in st.session_state:
                    st.session_state[page_key] = 1
                
                # Ensure the page number is within bounds
                if st.session_state[page_key] > total_pages:
                    st.session_state[page_key] = total_pages
                if st.session_state[page_key] < 1:
                    st.session_state[page_key] = 1
                
                # Controls layout
                c1, c2, c3, c4 = st.columns([1, 1, 1.2, 3])
                
                with c1:
                    if st.button("⬅️ Prev", key=f"pdf_btn_prev_{source_name}_{key_suffix}", disabled=(st.session_state[page_key] == 1)):
                        st.session_state[page_key] -= 1
                        st.rerun()
                with c2:
                    if st.button("Next ➡️", key=f"pdf_btn_next_{source_name}_{key_suffix}", disabled=(st.session_state[page_key] == total_pages)):
                        st.session_state[page_key] += 1
                        st.rerun()
                with c3:
                    # Input to jump directly
                    val = st.number_input(
                        "Page Select",
                        min_value=1,
                        max_value=total_pages,
                        value=st.session_state[page_key],
                        key=f"pdf_val_input_{source_name}_{key_suffix}",
                        label_visibility="collapsed"
                    )
                    if val != st.session_state[page_key]:
                        st.session_state[page_key] = val
                        st.rerun()
                with c4:
                    st.markdown(f'<div style="padding-top:7px;font-size:12.5px;color:var(--text-muted);">'
                                f'Page <b style="color:var(--text-secondary)">{st.session_state[page_key]}</b>'
                                f' of <b style="color:var(--text-secondary)">{total_pages}</b></div>',
                                unsafe_allow_html=True)
                
                st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:8px 0 16px;">', unsafe_allow_html=True)
                
                # Extract text for current page
                page_text = pdf.pages[st.session_state[page_key] - 1].extract_text()
                if page_text and page_text.strip():
                    st.markdown(
                        f'<div class="fs-pdf-text-container" style="background:rgba(255,255,255,0.015);'
                        f'border:1px solid var(--border);border-radius:var(--radius-sm);'
                        f'padding:22px;line-height:1.75;font-family:\'Inter\',sans-serif;white-space:pre-wrap;color:#CBD5E1;">'
                        f'{page_text}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.info("No extractable text found on this page.")
        except Exception as exc:
            st.error(f"Could not extract text: {exc}")


# ── Database helpers ──────────────────────────────────────────────────────────
def get_user_documents(role: str) -> list[tuple]:
    role = role.lower()
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    if role == "c-level":
        c.execute("SELECT filename, filepath FROM documents")
    elif role == "general":
        c.execute("SELECT filename, filepath FROM documents WHERE LOWER(role)='general'")
    else:
        c.execute(
            "SELECT filename, filepath FROM documents WHERE LOWER(role)=? OR LOWER(role)='general'",
            (role,),
        )
    rows = c.fetchall()
    conn.close()
    return rows


def fetch_system_metrics() -> dict:
    metrics = {"docs": 0, "users": 0, "roles": 0, "tables": 0}
    try:
        import duckdb
        conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        metrics["docs"]  = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        metrics["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        metrics["roles"] = c.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
        conn.close()
        duck_path = os.path.join(BASE_DIR, "static", "data",
                                 os.getenv("DUCKDB_NAME", "structured_queries.duckdb"))
        dc = duckdb.connect(duck_path, read_only=True)
        metrics["tables"] = dc.execute("SELECT COUNT(*) FROM tables_metadata").fetchone()[0]
        dc.close()
    except Exception:
        pass
    return metrics


# ── API helpers ───────────────────────────────────────────────────────────────
def fetch_roles() -> list[str]:
    try:
        r = requests.get(f"{API_URL}/roles", headers=api_headers(), timeout=6)
        return r.json().get("roles", [])
    except Exception:
        return []


def fetch_bulk_status() -> dict | None:
    try:
        r = requests.get(f"{API_URL}/indexing-status-bulk", headers=api_headers(), timeout=8)
        return r.json() if r.ok else None
    except Exception:
        return None


# ── Source document expanders ─────────────────────────────────────────────────
def render_message_sources(sources: list[str], role: str, key_suffix: str = "") -> None:
    if not sources:
        return
    user_docs = get_user_documents(role)
    allowed   = {doc[0]: doc[1] for doc in user_docs}
    accessible = [(s, allowed[s]) for s in sources if s in allowed]
    if not accessible:
        return
    for src, filepath in accessible:
        ext  = os.path.splitext(src)[1].lower()
        icon = "📊" if ext == ".csv" else "📄" if ext == ".md" else "📑"
        with st.expander(f"{icon} Source: {src}"):
            try:
                if ext == ".csv":
                    display_paginated_df(pd.read_csv(filepath), f"ref_{src}_{key_suffix}", max_height=280)
                elif ext == ".md":
                    with open(filepath, "r", encoding="utf-8") as f:
                        st.markdown(f.read())
                elif ext == ".pdf":
                    show_pdf_preview(filepath, src, key_suffix=f"{key_suffix}_{src}")
            except Exception as exc:
                st.error(f"Error loading source: {exc}")
