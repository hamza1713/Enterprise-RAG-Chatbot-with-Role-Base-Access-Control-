"""
app/ui/pages/admin.py — Upload tab and Admin tab (C-Level only).

Extracted from the old monolithic `app/ui.py` (~400 lines).
Indexing status has been moved to app/ui/pages/kb_indexing.py.
"""

import time

import requests
import streamlit as st

from app.ui.constants import API_URL
from app.ui.helpers import api_headers


# ── Upload tab ────────────────────────────────────────────────────────────────
def render_upload_tab() -> None:
    """Render the document upload tab (C-Level only)."""
    st.markdown(
        '<div class="fs-section">'
        '<div class="fs-section-title">📤 Upload knowledge documents</div>'
        '<div class="fs-section-sub">Upload .md, .csv, or .pdf files to index into the RAG knowledge base.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    up1, up2 = st.columns([1, 1])
    with up1:
        selected_role = st.selectbox("Assign to role", st.session_state.get("roles", []), key="upload_role")
    with up2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        doc_file = st.file_uploader("Choose file", type=["csv", "md", "pdf"], key="doc_uploader")

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    if st.button("⬆️ Upload & Index Document", key="upload_btn"):
        if not doc_file:
            st.warning("Please select a file first.")
            return

        filename = doc_file.name
        res      = None
        with st.spinner("Uploading…"):
            try:
                res = requests.post(
                    f"{API_URL}/upload-docs",
                    files={"file": doc_file},
                    data={"role": selected_role},
                    headers=api_headers(),
                    timeout=60,
                )
                if not res.ok:
                    st.error(res.json().get("detail", "Upload failed."))
            except Exception as exc:
                st.error(f"Upload error: {exc}")

        if res and res.ok:
            st.info("File registered. Indexing started in background…")
            progress_bar = st.progress(0.0)
            status_text  = st.empty()
            success      = False

            for _ in range(400):
                try:
                    sr = requests.get(
                        f"{API_URL}/indexing-status",
                        params={"filename": filename},
                        headers=api_headers(),
                        timeout=10,
                    )
                    if sr.ok:
                        sd  = sr.json()
                        emb = sd.get("embedded", 0)
                        tc  = sd.get("total_chunks", 0)
                        ec  = sd.get("embedded_chunks", 0)
                        if emb == 1:
                            progress_bar.progress(1.0)
                            status_text.success(f"🎉 '{filename}' indexed successfully!")
                            success = True
                            break
                        elif emb < 0:
                            progress_bar.progress(0.0)
                            status_text.error(f"❌ '{filename}' failed to index. Check logs or retry from KB Indexing.")
                            break
                        if tc > 0:
                            pct = min(1.0, ec / tc)
                            progress_bar.progress(pct)
                            status_text.info(f"⏳ Embedding: {ec}/{tc} chunks ({int(pct*100)}%)")
                        else:
                            status_text.info("⏳ Parsing document…")
                    else:
                        status_text.warning("Waiting for indexing server…")
                except Exception as poll_err:
                    status_text.warning(f"Polling: {poll_err}")
                time.sleep(1.5)

            if not success:
                st.warning("⚠️ Indexing is taking longer than expected. It continues in the background — check KB Indexing tab.")


# ── Admin tab ─────────────────────────────────────────────────────────────────
def render_admin_tab() -> None:
    """Render the administrative controls tab (C-Level only).

    Indexing status has been moved to the dedicated KB Indexing tab.
    This tab now focuses on user and role management.
    """
    st.markdown(
        '<div class="fs-section">'
        '<div class="fs-section-title">⚙️ Administrative Controls</div>'
        '<div class="fs-section-sub">Manage system users and security roles.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # User & Role management
    adm1, adm2 = st.columns(2, gap="large")

    with adm1:
        st.markdown(
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);'
            'border-radius:10px;padding:18px 18px 4px;margin-bottom:12px;">'
            '<div style="font-weight:700;font-size:13.5px;color:#F1F5F9;margin-bottom:14px;">➕ Create system user</div>',
            unsafe_allow_html=True,
        )
        new_user = st.text_input("Username", key="adm_new_user", placeholder="Enter username")
        new_pass = st.text_input("Password", type="password", key="adm_new_pass", placeholder="Enter password")
        new_role = st.selectbox("Role", st.session_state.get("roles", []), key="adm_new_role")
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button("Create user", key="adm_create_user"):
            if not new_user.strip() or not new_pass.strip():
                st.warning("Fill in both username and password.")
            else:
                try:
                    r = requests.post(
                        f"{API_URL}/create-user",
                        data={"username": new_user, "password": new_pass, "role": new_role},
                        headers=api_headers(), timeout=10,
                    )
                    if r.ok:
                        st.success(r.json().get("message", "User created!"))
                    else:
                        st.error(r.json().get("detail", "Failed."))
                except Exception as exc:
                    st.error(f"Error: {exc}")

    with adm2:
        st.markdown(
            '<div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);'
            'border-radius:10px;padding:18px 18px 4px;margin-bottom:12px;">'
            '<div style="font-weight:700;font-size:13.5px;color:#F1F5F9;margin-bottom:14px;">🛡️ Add security role</div>',
            unsafe_allow_html=True,
        )
        new_role_name = st.text_input("Role name", key="adm_new_role_name", placeholder="e.g. Legal, Operations")
        st.markdown("</div>", unsafe_allow_html=True)
        if st.button("Add role", key="adm_add_role"):
            if not new_role_name.strip():
                st.warning("Enter a role name.")
            else:
                try:
                    r = requests.post(
                        f"{API_URL}/create-role",
                        data={"role_name": new_role_name.strip()},
                        headers=api_headers(), timeout=10,
                    )
                    if r.ok:
                        st.success(r.json().get("message", "Role added!"))
                        from app.ui.helpers import fetch_roles
                        st.session_state["roles"] = fetch_roles()
                        st.rerun()
                    else:
                        st.error(r.json().get("detail", "Failed."))
                except Exception as exc:
                    st.error(f"Error: {exc}")
