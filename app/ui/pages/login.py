"""
app/ui/pages/login.py — Login page.

Extracted from the old monolithic `app/ui.py` (~300 lines).
"""

import os
import requests
import streamlit as st

from app.ui.constants import API_URL, BASE_DIR, LOGIN_TIMEOUT


def render_login_page(bg_image_path: str) -> None:
    """Render the full-page login form and handle authentication."""
    # Optional animated background
    import base64
    if os.path.exists(bg_image_path):
        with open(bg_image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<style>.stApp{{background:linear-gradient(rgba(5,7,18,0.92),rgba(5,7,18,0.92)),'
            f'url("data:image/jpg;base64,{encoded}") center/cover fixed!important;}}</style>',
            unsafe_allow_html=True,
        )

    st.markdown("""
    <div style="text-align:center;padding:40px 0 28px;">
        <div style="display:inline-flex;align-items:center;gap:12px;margin-bottom:10px;">
            <div style="width:46px;height:46px;border-radius:14px;
                background:linear-gradient(135deg,var(--primary),var(--secondary));
                display:flex;align-items:center;justify-content:center;
                font-size:22px;box-shadow:0 4px 18px rgba(var(--accent-rgb),0.38);">📊</div>
            <span style="font-size:26px;font-weight:800;letter-spacing:-0.03em;
                color:#fff;">Fin<span style="color:var(--primary-hover)">Sight</span></span>
        </div>
        <div style="font-size:13px;color:var(--text-muted);font-style:italic;">
            Role-Based AI Workspace
        </div>
    </div>
    """, unsafe_allow_html=True)

    _, form_col, _ = st.columns([1, 1.4, 1])
    with form_col:
        with st.form("login_form"):
            st.markdown(
                '<div style="font-size:12px;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.08em;color:var(--text-muted);margin-bottom:4px;">Username</div>',
                unsafe_allow_html=True,
            )
            username = st.text_input(
                "Username", placeholder="Enter your username",
                label_visibility="collapsed",
            )
            st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
            st.markdown(
                '<div style="font-size:12px;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.08em;color:var(--text-muted);margin-bottom:4px;">Password</div>',
                unsafe_allow_html=True,
            )
            password = st.text_input(
                "Password", type="password",
                placeholder="Enter your password",
                label_visibility="collapsed",
            )
            st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Sign In →", use_container_width=True)

        if submitted:
            if not username.strip() or not password.strip():
                st.error("Please enter both username and password.")
                return
            try:
                resp = requests.get(
                    f"{API_URL}/login",
                    auth=(username.strip(), password.strip()),
                    timeout=LOGIN_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state["authenticated"] = True
                    st.session_state["username"]      = username.strip()
                    st.session_state["role"]          = data.get("role", "General")
                    st.session_state["token"]         = data.get("access_token", "")
                    st.rerun()
                elif resp.status_code == 401:
                    st.error("Invalid username or password.")
                else:
                    st.error(f"Login failed (HTTP {resp.status_code}). Please try again.")
            except requests.exceptions.ConnectionError:
                st.error("🔌 Could not connect to the backend. Is the FastAPI server running?")
            except requests.exceptions.Timeout:
                st.warning(f"⏱️ Connection timed out after {LOGIN_TIMEOUT}s. Please retry.")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")

        st.markdown("""
        <div style="text-align:center;margin-top:22px;font-size:11.5px;color:var(--text-muted);">
            🔒 Secured with JWT Authentication
        </div>
        """, unsafe_allow_html=True)
