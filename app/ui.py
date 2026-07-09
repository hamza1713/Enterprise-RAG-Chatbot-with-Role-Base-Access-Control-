"""
app/ui.py — Streamlit entry point.

This file is now a thin orchestrator (~80 lines).
All logic has been moved to:
  - app/ui/styles.py    — CSS injection & theme definitions
  - app/ui/constants.py — API URL, paths, role colours
  - app/ui/helpers.py   — Shared API/DB helpers
  - app/ui/pages/login.py  — Login page
  - app/ui/pages/chat.py   — Chat + Document Explorer tabs
  - app/ui/pages/admin.py  — Upload + Admin tabs (C-Level only)
"""

import os
import streamlit as st

from app.ui.constants import BASE_DIR
from app.ui.styles import inject_global_css, THEME_OPTIONS
from app.ui.helpers import fetch_roles
from app.ui.pages.login import render_login_page
from app.ui.pages.chat import render_sidebar, render_chat_tab, render_explorer_tab
from app.ui.pages.admin import render_upload_tab, render_admin_tab
from app.ui.pages.kb_indexing import render_kb_indexing_tab

# ── Streamlit page config (must be first Streamlit call) ──────────────────────
st.set_page_config(
    page_title="FinSight — AI Workspace",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Static asset paths ────────────────────────────────────────────────────────
BG_IMAGE: str = os.path.join(BASE_DIR, "static", "images", "bg.jpg")

# ── Session defaults ──────────────────────────────────────────────────────────
st.session_state.setdefault("authenticated", False)
st.session_state.setdefault("theme",         THEME_OPTIONS[0])
st.session_state.setdefault("messages",      [])

# ── CSS (inject before any visible element) ───────────────────────────────────
inject_global_css(BG_IMAGE, theme_name=st.session_state.get("theme", THEME_OPTIONS[0]))


# ════════════════════════════════════════════════════════════════════════════════
#  ROUTING
# ════════════════════════════════════════════════════════════════════════════════

if not st.session_state["authenticated"]:
    render_login_page(BG_IMAGE)
else:
    username = st.session_state.get("username", "User")
    role     = st.session_state.get("role",     "General")

    # Initialise roles list once per session
    if "roles" not in st.session_state:
        st.session_state["roles"] = fetch_roles()

    # Sidebar (returns selected theme name)
    new_theme = render_sidebar(
        username     = username,
        role         = role,
        theme_name   = st.session_state.get("theme", THEME_OPTIONS[0]),
        theme_options= THEME_OPTIONS,
    )
    if new_theme != st.session_state.get("theme"):
        st.session_state["theme"] = new_theme
        st.rerun()

    # ── Tab layout ────────────────────────────────────────────────────────────
    if role == "C-Level":
        chat_tab, explorer_tab, upload_tab, kb_tab, admin_tab = st.tabs([
            "💬 AI Chat", "📄 Explorer", "📤 Upload", "🗂️ KB Indexing", "⚙️ Admin",
        ])
    else:
        chat_tab, explorer_tab = st.tabs(["💬 AI Chat", "📄 Explorer"])
        upload_tab = kb_tab = admin_tab = None

    with chat_tab:
        render_chat_tab(role)

    with explorer_tab:
        render_explorer_tab(role)

    if role == "C-Level":
        with upload_tab:
            render_upload_tab()
        with kb_tab:
            render_kb_indexing_tab()
        with admin_tab:
            render_admin_tab()