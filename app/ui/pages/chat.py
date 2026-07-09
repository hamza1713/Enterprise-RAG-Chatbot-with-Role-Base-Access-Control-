"""
app/ui/pages/chat.py — Chat tab and Document Explorer tab.

Extracted from the old monolithic `app/ui.py` (~700 lines).
"""

import json
import time
import asyncio

import requests
import streamlit as st

from app.ui.constants import API_URL, ROLE_COLORS, LOGIN_TIMEOUT
from app.ui.helpers import (
    api_headers,
    display_paginated_df,
    show_pdf_preview,
    get_user_documents,
    render_message_sources,
)


# ── Sidebar helpers ───────────────────────────────────────────────────────────
def render_sidebar(username: str, role: str, theme_name: str, theme_options: list[str]) -> str:
    """Render the left sidebar. Returns the (potentially updated) theme name."""
    with st.sidebar:
        # Logo
        st.markdown("""
        <div style="padding:22px 0 14px;text-align:center;">
            <div style="display:inline-flex;align-items:center;gap:9px;">
                <div style="width:36px;height:36px;border-radius:10px;
                    background:linear-gradient(135deg,var(--primary),var(--secondary));
                    display:flex;align-items:center;justify-content:center;
                    font-size:17px;box-shadow:0 3px 10px rgba(var(--accent-rgb),0.35);">📊</div>
                <span style="font-size:19px;font-weight:800;letter-spacing:-0.03em;color:#fff;">
                    Fin<span style="color:var(--primary-hover)">Sight</span>
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # User card
        role_color = ROLE_COLORS.get(role, "#6366F1")
        st.markdown(f"""
        <div style="background:rgba(14,18,46,0.7);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:12px 14px;margin:0 0 16px;display:flex;
            align-items:center;gap:10px;">
            <div style="width:36px;height:36px;border-radius:10px;
                background:linear-gradient(135deg,rgba(var(--accent-rgb),0.2),rgba(var(--accent-rgb),0.1));
                border:1px solid rgba(var(--accent-rgb),0.25);display:flex;align-items:center;
                justify-content:center;font-size:15px;flex-shrink:0;">
                {'👑' if role=='C-Level' else '👤'}
            </div>
            <div style="overflow:hidden;">
                <div style="font-size:13.5px;font-weight:700;color:#F8FAFC;
                    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                    {username}
                </div>
                <div style="font-size:11px;font-weight:600;color:{role_color};
                    text-transform:uppercase;letter-spacing:0.07em;">
                    {role}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Theme selector
        st.markdown('<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:6px;">Interface Theme</div>', unsafe_allow_html=True)
        selected_theme = st.selectbox(
            "Theme", theme_options,
            index=theme_options.index(theme_name) if theme_name in theme_options else 0,
            label_visibility="collapsed", key="theme_selector",
        )
        st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:14px 0 16px;">', unsafe_allow_html=True)

        # System metrics (Admin / C-Level only)
        if role == "C-Level":
            try:
                from app.ui.helpers import fetch_system_metrics
                m = fetch_system_metrics()
                st.markdown(f"""
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
                    <div class="fs-metric-card" style="padding:10px 8px;">
                        <span class="fs-metric-label">Docs</span>
                        <div class="fs-metric-value" style="font-size:22px;color:var(--primary-hover);">{m['docs']}</div>
                    </div>
                    <div class="fs-metric-card" style="padding:10px 8px;">
                        <span class="fs-metric-label">Users</span>
                        <div class="fs-metric-value" style="font-size:22px;color:#10B981;">{m['users']}</div>
                    </div>
                    <div class="fs-metric-card" style="padding:10px 8px;">
                        <span class="fs-metric-label">Roles</span>
                        <div class="fs-metric-value" style="font-size:22px;color:#F59E0B;">{m['roles']}</div>
                    </div>
                    <div class="fs-metric-card" style="padding:10px 8px;">
                        <span class="fs-metric-label">Tables</span>
                        <div class="fs-metric-value" style="font-size:22px;color:#A78BFA;">{m['tables']}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            except Exception:
                pass

        st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:0 0 14px;">', unsafe_allow_html=True)

        # Sign out
        if st.button("🚪 Sign Out", use_container_width=True, key="signout_btn"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        # API status
        try:
            api_ok = requests.get(f"{API_URL}/", timeout=2).status_code == 200
        except Exception:
            api_ok = False
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:7px;font-size:11px;'
            f'color:var(--text-muted);margin-top:14px;">'
            f'<span class="fs-online" style="background:{"#10B981" if api_ok else "#EF4444"};animation:{"fs-pulse 2.2s infinite" if api_ok else "none"};"></span>'
            f'API {"online" if api_ok else "offline"}</div>',
            unsafe_allow_html=True,
        )

    return selected_theme


# ── Chat tab ──────────────────────────────────────────────────────────────────
def render_chat_tab(role: str) -> None:
    """Render the chat interface tab."""
    st.markdown(
        '<div class="fs-section">'
        '<div class="fs-section-title">💬 AI Chat</div>'
        '<div class="fs-section-sub">Ask questions about your workspace data — documents, tables, and reports.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    messages_container = st.container()
    with messages_container:
        if not st.session_state.get("messages"):
            st.markdown("""
            <div class="fs-empty-state">
                <div class="fs-empty-icon">💬</div>
                <div class="fs-empty-title">Start a conversation</div>
                <div class="fs-empty-sub">
                    Ask anything about your accessible documents. FinSight will automatically
                    choose between document search (RAG) and structured data queries (SQL).
                </div>
                <div>
                    <span class="fs-pill">📊 Show me my financial data</span>
                    <span class="fs-pill">📄 Summarize the HR policy</span>
                    <span class="fs-pill">📈 Marketing vs Finance spend</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant":
                        badges_html = ""
                        msg_mode = msg.get("mode", "RAG")
                        if msg_mode not in ("GREETING", "DENIED"):
                            if msg.get("sql"):
                                badges_html += '<span class="fs-badge fs-badge-sql">📊 SQL query</span>'
                            else:
                                badges_html += '<span class="fs-badge fs-badge-rag">📄 RAG document</span>'
                        if msg.get("fallback"):
                            badges_html += '<span class="fs-badge fs-badge-fallback">↩ Fallback</span>'
                        if badges_html:
                            st.markdown(badges_html, unsafe_allow_html=True)
                        if msg.get("sources"):
                            render_message_sources(msg["sources"], role, key_suffix=f"msg_{st.session_state.messages.index(msg)}")

    question = st.chat_input("Ask a question about your workspace data…", key="chat_input_main")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with messages_container:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                thinking_ph = st.empty()
                thinking_ph.markdown(
                    '<div class="fs-thinking">'
                    '<span class="fs-dot"></span>'
                    '<span class="fs-dot"></span>'
                    '<span class="fs-dot"></span>'
                    '<span style="margin-left:4px;">Thinking…</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                response_ph  = st.empty()
                full_response = ""
                state = {"mode": "RAG", "sql": None, "sources": [], "fallback": False}

                try:
                    res = requests.post(
                        f"{API_URL}/chat-stream",
                        json={"question": question},
                        headers=api_headers(),
                        stream=True,
                        timeout=(LOGIN_TIMEOUT, 120),
                    )
                    if res.status_code == 200:
                        first_chunk = True
                        for line in res.iter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line.decode("utf-8"))
                            except Exception:
                                continue
                            t = data.get("type")
                            if t == "init":
                                state["mode"] = data.get("mode", "RAG")
                            elif t == "fallback":
                                state["mode"]     = data.get("mode", "SQL → fallback to RAG")
                                state["fallback"] = True
                            elif t == "token":
                                if first_chunk:
                                    thinking_ph.empty()
                                    first_chunk = False
                                full_response += data.get("content", "")
                                response_ph.markdown(
                                    full_response + '<span class="fs-cursor"></span>',
                                    unsafe_allow_html=True,
                                )
                            elif t == "metadata":
                                state["sql"]      = data.get("sql")
                                state["sources"]  = data.get("sources", [])
                                state["fallback"] = data.get("fallback", False)
                            elif t == "error":
                                if first_chunk:
                                    thinking_ph.empty()
                                    first_chunk = False
                                full_response = data.get("answer", "Something went wrong.")
                                response_ph.markdown(full_response)
                    else:
                        thinking_ph.empty()
                        full_response = "❌ Server error. Please try again."
                        response_ph.markdown(full_response)
                except requests.exceptions.ConnectionError:
                    thinking_ph.empty()
                    full_response = "🔌 **Backend offline** — please restart the FastAPI server."
                    response_ph.markdown(full_response)
                except requests.exceptions.Timeout:
                    thinking_ph.empty()
                    full_response = "⏱️ **Request timed out** — the server took too long to respond."
                    response_ph.markdown(full_response)
                except Exception as exc:
                    thinking_ph.empty()
                    full_response = f"⚠️ Unexpected error: {exc}"
                    response_ph.markdown(full_response)

                response_ph.markdown(full_response)

                # Badges
                sql      = state.get("sql")
                sources  = state.get("sources", [])
                fallback = state.get("fallback", False)
                cur_mode = state.get("mode", "RAG")
                badges_html = ""
                if cur_mode not in ("GREETING", "DENIED"):
                    badges_html = (
                        '<span class="fs-badge fs-badge-sql">📊 SQL query</span>'
                        if sql else
                        '<span class="fs-badge fs-badge-rag">📄 RAG document</span>'
                    )
                if fallback:
                    badges_html += '<span class="fs-badge fs-badge-fallback">↩ Fallback</span>'
                if badges_html:
                    st.markdown(badges_html, unsafe_allow_html=True)

                render_message_sources(sources, role, key_suffix=f"msg_{len(st.session_state.messages)}")

                msg_record = {
                    "role": "assistant", "content": full_response,
                    "mode": state.get("mode", "RAG"),
                    "sources": sources, "fallback": fallback,
                }
                if sql:
                    msg_record["sql"] = sql
                st.session_state.messages.append(msg_record)

    if st.session_state.get("messages"):
        _, clear_col = st.columns([7, 1])
        with clear_col:
            if st.button("🗑️ Clear", key="clear_chat", help="Clear conversation"):
                st.session_state.messages = []
                st.rerun()


# ── Document Explorer tab ─────────────────────────────────────────────────────
def render_explorer_tab(role: str) -> None:
    """Render the document explorer tab."""
    import os
    import pandas as pd

    st.markdown(
        '<div class="fs-section">'
        '<div class="fs-section-title">📄 Document Explorer</div>'
        '<div class="fs-section-sub">Browse and preview documents available to your role.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    user_docs = get_user_documents(role)
    if not user_docs:
        st.info("No documents indexed or available for your role.")
        return

    doc_names    = [d[0] for d in user_docs]
    sel_col, _   = st.columns([2, 3])
    with sel_col:
        selected_doc = st.selectbox("Select document", ["— Select —"] + doc_names, key="exp_sel")

    if not selected_doc or selected_doc == "— Select —":
        return

    selected_path = next(d[1] for d in user_docs if d[0] == selected_doc)
    ext           = os.path.splitext(selected_path)[1].lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(selected_path)
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">'
                f'<span style="font-size:18px;">📊</span>'
                f'<div><div style="font-weight:600;font-size:14px;color:#F1F5F9;">{selected_doc}</div>'
                f'<div style="font-size:11.5px;color:var(--text-muted);">{len(df)} rows · {len(df.columns)} columns</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            with st.expander("🔍 Filters", expanded=False):
                fc1, fc2, fc3 = st.columns([1.5, 1.5, 2])
                cols_list    = ["— No filter —"] + list(df.columns)
                filter_col   = fc1.selectbox("Column", cols_list, key="exp_fcol")
                filtered     = df.copy()
                if filter_col != "— No filter —":
                    import numpy as np
                    is_num   = np.issubdtype(df[filter_col].dtype, np.number)
                    conditions = ["Contains", "Equals", "Starts with"]
                    if is_num:
                        conditions += ["> Greater than", "< Less than", ">= At least", "<= At most"]
                    cond = fc2.selectbox("Condition", conditions, key="exp_fcond")
                    if is_num:
                        val  = fc3.number_input("Value", value=0.0, key="exp_fval_n")
                        ops  = {
                            "Equals":       lambda c: filtered[c] == val,
                            "> Greater than": lambda c: filtered[c] > val,
                            "< Less than":  lambda c: filtered[c] < val,
                            ">= At least":  lambda c: filtered[c] >= val,
                            "<= At most":   lambda c: filtered[c] <= val,
                            "Contains":     lambda c: filtered[c].astype(str).str.contains(str(val), case=False, na=False),
                        }
                        if cond in ops:
                            filtered = filtered[ops[cond](filter_col)]
                    else:
                        val  = fc3.text_input("Value", key="exp_fval_t")
                        if val:
                            if cond == "Contains":
                                filtered = filtered[filtered[filter_col].astype(str).str.contains(val, case=False, na=False)]
                            elif cond == "Equals":
                                filtered = filtered[filtered[filter_col].astype(str).str.lower() == val.lower()]
                            elif cond == "Starts with":
                                filtered = filtered[filtered[filter_col].astype(str).str.lower().str.startswith(val.lower())]
            display_paginated_df(filtered, "explorer", total_original_rows=len(df))

        elif ext == ".md":
            with open(selected_path, "r", encoding="utf-8") as f:
                st.markdown(f.read())

        elif ext == ".pdf":
            show_pdf_preview(selected_path, selected_doc, key_suffix="explorer")
        else:
            st.warning(f"Preview not available for `{ext}` files.")
    except Exception as exc:
        st.error(f"Error reading file: {exc}")
