"""
app/ui/styles.py — Global CSS injection and shared theme definitions.

Extracted from the old monolithic `app/ui.py`.
"""

import os
import base64

import streamlit as st


# ── Theme palettes ────────────────────────────────────────────────────────────
THEMES: dict[str, dict] = {
    "Indigo Nebula": {
        "primary": "#6366F1", "primary_hover": "#818CF8",
        "secondary": "#8B5CF6", "secondary_hover": "#A78BFA",
        "accent_rgb": "99,102,241",
        "bg": "linear-gradient(160deg, #07091a 0%, #0d1130 55%, #060914 100%)",
        "surface": "rgba(14,17,42,0.92)", "surface_2": "rgba(20,25,58,0.7)",
        "border": "rgba(99,102,241,0.15)", "border_hover": "rgba(99,102,241,0.35)",
        "user_bubble": "rgba(99,102,241,0.1)", "user_border": "rgba(99,102,241,0.25)",
    },
    "Emerald Aurora": {
        "primary": "#10B981", "primary_hover": "#34D399",
        "secondary": "#059669", "secondary_hover": "#6EE7B7",
        "accent_rgb": "16,185,129",
        "bg": "linear-gradient(160deg, #030d08 0%, #071a10 55%, #020a06 100%)",
        "surface": "rgba(10,22,15,0.92)", "surface_2": "rgba(14,32,22,0.7)",
        "border": "rgba(16,185,129,0.15)", "border_hover": "rgba(16,185,129,0.35)",
        "user_bubble": "rgba(16,185,129,0.08)", "user_border": "rgba(16,185,129,0.22)",
    },
    "Nordic Blizzard": {
        "primary": "#06B6D4", "primary_hover": "#22D3EE",
        "secondary": "#3B82F6", "secondary_hover": "#93C5FD",
        "accent_rgb": "6,182,212",
        "bg": "linear-gradient(160deg, #020810 0%, #05142a 55%, #020810 100%)",
        "surface": "rgba(8,16,36,0.92)", "surface_2": "rgba(12,24,52,0.7)",
        "border": "rgba(6,182,212,0.15)", "border_hover": "rgba(6,182,212,0.35)",
        "user_bubble": "rgba(6,182,212,0.08)", "user_border": "rgba(6,182,212,0.22)",
    },
    "Crimson Eclipse": {
        "primary": "#F43F5E", "primary_hover": "#FB7185",
        "secondary": "#A855F7", "secondary_hover": "#D946EF",
        "accent_rgb": "244,63,94",
        "bg": "linear-gradient(160deg, #100108 0%, #200312 55%, #0f0107 100%)",
        "surface": "rgba(20,4,12,0.92)", "surface_2": "rgba(30,6,18,0.7)",
        "border": "rgba(244,63,94,0.15)", "border_hover": "rgba(244,63,94,0.35)",
        "user_bubble": "rgba(244,63,94,0.08)", "user_border": "rgba(244,63,94,0.22)",
    },
}

THEME_OPTIONS: list[str] = list(THEMES.keys())


def inject_global_css(image_path: str, theme_name: str = "Indigo Nebula") -> None:
    """Inject the full FinSight dark theme CSS into the Streamlit app."""
    encoded = ""
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()

    t = THEMES.get(theme_name, THEMES["Indigo Nebula"])
    bg_style = (
        f'background: linear-gradient(rgba(7,9,22,0.94), rgba(7,9,22,0.94)), '
        f'url("data:image/jpg;base64,{encoded}") center/cover fixed !important;'
        if encoded else f"background: {t['bg']} !important;"
    )

    css = f"""
<style>
:root {{
    --primary: {t['primary']};
    --primary-hover: {t['primary_hover']};
    --secondary: {t['secondary']};
    --accent-rgb: {t['accent_rgb']};
    --surface: {t['surface']};
    --surface-2: {t['surface_2']};
    --border: {t['border']};
    --border-hover: {t['border_hover']};
    --user-bubble: {t['user_bubble']};
    --user-border: {t['user_border']};
    --text-primary: #F1F5F9;
    --text-secondary: #94A3B8;
    --text-muted: #475569;
    --radius-sm: 8px; --radius-md: 12px; --radius-lg: 16px; --radius-xl: 20px;
}}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', -apple-system, sans-serif !important; color: var(--text-primary) !important; -webkit-font-smoothing: antialiased; }}
.stApp {{ {bg_style} min-height: 100vh; }}
[data-testid="stHeader"], header, footer, #MainMenu {{
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}}
::-webkit-scrollbar {{ width: 4px; height: 4px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border-hover); border-radius: 99px; }}
[data-testid="stSidebar"] {{ background: rgba(8,11,28,0.97) !important; border-right: 1px solid var(--border) !important; backdrop-filter: blur(24px); }}
[data-testid="stSidebar"] > div:first-child {{ padding-top: 0 !important; }}
.block-container {{ padding: 1.25rem 1.75rem 3rem 1.75rem !important; max-width: 100% !important; }}
.stMarkdown p, .stMarkdown li {{ color: #CBD5E1 !important; line-height: 1.75 !important; }}
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{ color: #F8FAFC !important; font-weight: 600 !important; letter-spacing: -0.02em; }}
label {{ color: var(--text-secondary) !important; font-weight: 500 !important; font-size: 12px !important; text-transform: uppercase !important; letter-spacing: 0.05em !important; }}
div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea {{ background: rgba(10,14,34,0.85) !important; color: var(--text-primary) !important; border: 1px solid var(--border) !important; border-radius: var(--radius-sm) !important; transition: border-color 0.2s; }}
div[data-baseweb="input"] input:focus, div[data-baseweb="textarea"] textarea:focus {{ border-color: var(--primary) !important; box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.12) !important; }}
div[data-baseweb="select"] > div {{ background: rgba(10,14,34,0.85) !important; border-color: var(--border) !important; color: var(--text-primary) !important; border-radius: var(--radius-sm) !important; }}
div.stButton > button {{ background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%) !important; color: white !important; font-weight: 600 !important; font-size: 13.5px !important; padding: 0.55rem 1.4rem !important; border-radius: var(--radius-sm) !important; border: none !important; box-shadow: 0 2px 12px rgba(var(--accent-rgb), 0.28) !important; transition: all 0.2s ease !important; width: 100% !important; letter-spacing: 0.01em; }}
div.stButton > button:hover {{ box-shadow: 0 4px 20px rgba(var(--accent-rgb), 0.4) !important; transform: translateY(-1px) !important; filter: brightness(1.08); }}
div.stButton > button:active {{ transform: translateY(0) !important; }}
form[data-testid="stForm"] {{ background: rgba(10,14,34,0.88) !important; backdrop-filter: blur(40px) !important; border: 1px solid var(--border) !important; border-radius: var(--radius-xl) !important; padding: 42px 38px !important; box-shadow: 0 32px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.03) !important; }}
form[data-testid="stForm"] button[type="submit"] {{ background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%) !important; color: white !important; font-weight: 600 !important; border-radius: var(--radius-sm) !important; border: none !important; width: 100% !important; padding: 0.65rem 1.4rem !important; font-size: 14px !important; letter-spacing: 0.01em; }}
button[data-baseweb="tab"] {{ color: var(--text-muted) !important; font-weight: 500 !important; font-size: 13.5px !important; padding: 10px 20px !important; border-bottom: 2px solid transparent !important; transition: color 0.18s, border-color 0.18s; background: transparent !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: var(--primary-hover) !important; font-weight: 600 !important; border-bottom-color: var(--primary-hover) !important; background: transparent !important; }}
[data-testid="stTabs"] > div:first-child {{ border-bottom: 1px solid var(--border) !important; margin-bottom: 1.25rem; }}
div[data-testid="stExpander"] {{ background: var(--surface-2) !important; border: 1px solid var(--border) !important; border-radius: var(--radius-md) !important; }}
div[data-testid="stChatMessage"] {{ background: transparent !important; border: none !important; padding: 0 !important; margin-bottom: 2px !important; }}
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{ background: var(--user-bubble) !important; border: 1px solid var(--user-border) !important; border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg) !important; padding: 14px 18px 14px 16px !important; margin-left: 12% !important; margin-right: 0 !important; margin-bottom: 12px !important; }}
div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {{ background: rgba(14,18,42,0.72) !important; border: 1px solid rgba(255,255,255,0.055) !important; border-radius: var(--radius-lg) var(--radius-lg) var(--radius-lg) 4px !important; padding: 16px 20px 14px 18px !important; margin-right: 8% !important; margin-bottom: 12px !important; backdrop-filter: blur(12px); }}
div[data-testid="stChatMessage"] p {{ color: #E2E8F0 !important; font-size: 14.5px !important; line-height: 1.78 !important; margin-bottom: 0.4em !important; }}
div[data-testid="stChatMessage"] li {{ color: #CBD5E1 !important; line-height: 1.75 !important; }}
div[data-testid="stChatMessage"] code {{ background: rgba(var(--accent-rgb), 0.12) !important; color: var(--primary-hover) !important; border-radius: 4px !important; padding: 1px 6px !important; font-family: 'JetBrains Mono', monospace !important; font-size: 13px !important; }}
div[data-testid="stChatMessage"] pre {{ background: rgba(6,8,20,0.7) !important; border: 1px solid var(--border) !important; border-radius: var(--radius-sm) !important; padding: 14px 16px !important; }}
[data-testid="chatAvatarIcon-user"], [data-testid="chatAvatarIcon-assistant"] {{ width: 30px !important; height: 30px !important; border-radius: 8px !important; font-size: 13px !important; }}
[data-testid="chatAvatarIcon-assistant"] {{ background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%) !important; border: none !important; }}
[data-testid="chatAvatarIcon-user"] {{ background: rgba(var(--accent-rgb), 0.18) !important; border: 1px solid var(--border-hover) !important; }}
div[data-testid="stChatInputContainer"] {{ background: rgba(10,14,34,0.92) !important; border: 1px solid var(--border-hover) !important; border-radius: var(--radius-lg) !important; box-shadow: 0 0 0 4px rgba(var(--accent-rgb), 0.06), 0 8px 32px rgba(0,0,0,0.35) !important; backdrop-filter: blur(20px) !important; padding: 6px 6px 6px 8px !important; transition: border-color 0.25s, box-shadow 0.25s; }}
div[data-testid="stChatInputContainer"]:focus-within {{ border-color: var(--primary) !important; box-shadow: 0 0 0 4px rgba(var(--accent-rgb), 0.14), 0 12px 40px rgba(0,0,0,0.4) !important; }}
textarea[data-testid="stChatInputTextArea"] {{ background: transparent !important; color: var(--text-primary) !important; font-size: 14.5px !important; line-height: 1.6 !important; border: none !important; padding: 8px 4px !important; font-family: 'Inter', sans-serif !important; }}
[data-testid="stChatInputContainer"] button {{ background: linear-gradient(135deg, var(--primary), var(--secondary)) !important; border-radius: 10px !important; border: none !important; width: 36px !important; height: 36px !important; min-height: 36px !important; box-shadow: 0 2px 10px rgba(var(--accent-rgb), 0.35) !important; transition: all 0.2s !important; }}
[data-testid="stChatInputContainer"] button:hover {{ box-shadow: 0 4px 18px rgba(var(--accent-rgb), 0.5) !important; transform: scale(1.05) !important; }}
[data-testid="stFileUploaderDropzone"] {{ background: rgba(14,18,42,0.6) !important; border: 2px dashed var(--border-hover) !important; border-radius: var(--radius-md) !important; transition: border-color 0.2s, background 0.2s; }}
[data-testid="stFileUploaderDropzone"]:hover {{ background: rgba(var(--accent-rgb), 0.05) !important; border-color: var(--primary) !important; }}
[data-testid="stProgress"] > div > div {{ background: linear-gradient(90deg, var(--primary), var(--secondary)) !important; border-radius: 99px !important; }}
[data-testid="stProgress"] > div {{ background: rgba(255,255,255,0.06) !important; border-radius: 99px !important; }}
div[data-testid="stAlert"] {{ border-radius: var(--radius-sm) !important; border-left-width: 3px !important; font-size: 13.5px !important; }}
.fs-metric-card {{ background: rgba(14,18,46,0.75); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 20px 18px; text-align: center; transition: border-color 0.2s, transform 0.2s; }}
.fs-metric-card:hover {{ border-color: var(--border-hover); transform: translateY(-2px); }}
.fs-metric-label {{ font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-muted); margin-bottom: 10px; display: block; }}
.fs-metric-value {{ font-size: 34px; font-weight: 700; letter-spacing: -0.04em; line-height: 1; }}
.fs-thinking {{ display: flex; align-items: center; gap: 10px; padding: 6px 0; color: var(--text-muted); font-size: 13.5px; font-style: italic; }}
.fs-dot {{ display: inline-block; width: 6px; height: 6px; background: var(--primary); border-radius: 50%; animation: fs-bounce 1.4s infinite ease-in-out; opacity: 0.8; }}
.fs-dot:nth-child(2) {{ animation-delay: 0.18s; }}
.fs-dot:nth-child(3) {{ animation-delay: 0.36s; }}
@keyframes fs-bounce {{ 0%, 80%, 100% {{ transform: scale(0.65); opacity: 0.3; }} 40% {{ transform: scale(1.1); opacity: 1; }} }}
.fs-cursor {{ display: inline-block; width: 2px; height: 16px; background: var(--primary-hover); border-radius: 1px; margin-left: 2px; vertical-align: text-bottom; animation: fs-blink 1.1s step-end infinite; }}
@keyframes fs-blink {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0; }} }}
.fs-badge {{ display: inline-flex; align-items: center; gap: 5px; font-size: 10.5px; font-weight: 700; padding: 3px 9px; border-radius: 6px; margin-top: 10px; margin-right: 6px; text-transform: uppercase; letter-spacing: 0.04em; vertical-align: middle; }}
.fs-badge-sql {{ background: rgba(59,130,246,0.1); color: #93C5FD; border: 1px solid rgba(59,130,246,0.2); }}
.fs-badge-rag {{ background: rgba(var(--accent-rgb), 0.1); color: var(--primary-hover); border: 1px solid rgba(var(--accent-rgb), 0.2); }}
.fs-badge-fallback {{ background: rgba(251,191,36,0.1); color: #FCD34D; border: 1px solid rgba(251,191,36,0.2); }}
.fs-hero {{ background: rgba(14,18,46,0.55); backdrop-filter: blur(20px); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 22px 28px; margin-bottom: 22px; display: flex; align-items: center; gap: 18px; }}
.fs-hero-icon {{ width: 48px; height: 48px; border-radius: 14px; background: linear-gradient(135deg, var(--primary), var(--secondary)); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; box-shadow: 0 4px 14px rgba(var(--accent-rgb), 0.3); }}
.fs-hero-title {{ font-size: 19px !important; font-weight: 700 !important; color: #FFFFFF !important; margin: 0 0 3px 0 !important; letter-spacing: -0.02em; }}
.fs-hero-sub {{ color: var(--text-secondary) !important; font-size: 13px !important; margin: 0 !important; }}
.fs-section {{ background: rgba(13,17,45,0.65); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 18px 22px; margin-bottom: 18px; }}
.fs-section-title {{ font-size: 15px; font-weight: 700; color: #F1F5F9 !important; margin: 0 0 3px; }}
.fs-section-sub {{ font-size: 12.5px; color: var(--text-muted) !important; margin: 0 0 16px; }}
.fs-table-wrap {{ width: 100%; overflow-x: auto; overflow-y: auto; max-height: 440px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: rgba(8,12,30,0.65); }}
.fs-table-wrap table {{ border-collapse: collapse; min-width: 100%; font-size: 12.5px; color: #CBD5E1; }}
.fs-table-wrap th {{ background: rgba(20,26,62,0.98) !important; color: var(--primary-hover) !important; font-weight: 600 !important; font-size: 11px !important; text-transform: uppercase !important; letter-spacing: 0.06em !important; padding: 10px 14px !important; position: sticky; top: 0; border-bottom: 1px solid var(--border) !important; white-space: nowrap; }}
.fs-table-wrap td {{ padding: 8px 14px; border-bottom: 1px solid rgba(255,255,255,0.035); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }}
.fs-table-wrap tr:hover td {{ background: rgba(var(--accent-rgb), 0.04); }}
.fs-table-info {{ display: flex; justify-content: space-between; padding: 7px 14px; background: rgba(12,16,40,0.5); border: 1px solid var(--border); border-top: none; border-radius: 0 0 var(--radius-sm) var(--radius-sm); font-size: 11.5px; color: var(--text-muted); }}
.fs-online {{ display: inline-block; width: 7px; height: 7px; background: #10B981; border-radius: 50%; animation: fs-pulse 2.2s infinite; flex-shrink: 0; }}
@keyframes fs-pulse {{ 0%, 100% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0.5); }} 50% {{ box-shadow: 0 0 0 5px rgba(16,185,129,0); }} }}
.fs-empty-state {{ text-align: center; padding: 56px 20px 40px; }}
.fs-empty-icon {{ font-size: 44px; margin-bottom: 14px; opacity: 0.6; }}
.fs-empty-title {{ font-size: 17px; font-weight: 600; color: var(--text-secondary) !important; margin-bottom: 8px; }}
.fs-empty-sub {{ font-size: 13.5px; color: var(--text-muted) !important; max-width: 400px; margin: 0 auto 28px; line-height: 1.65; }}
.fs-pill {{ display: inline-block; background: rgba(var(--accent-rgb), 0.07); border: 1px solid rgba(var(--accent-rgb), 0.18); border-radius: 20px; padding: 7px 15px; font-size: 12.5px; color: var(--primary-hover); margin: 4px; cursor: pointer; transition: background 0.18s, border-color 0.18s; }}
.fs-pill:hover {{ background: rgba(var(--accent-rgb), 0.13); border-color: rgba(var(--accent-rgb), 0.35); }}
.fs-admin-table {{ width: 100%; border-collapse: collapse; }}
.fs-admin-table th {{ padding: 9px 12px; text-align: left; font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.07em; background: rgba(255,255,255,0.025); border-bottom: 1px solid rgba(255,255,255,0.07); }}
.fs-admin-table td {{ padding: 10px 12px; font-size: 12.5px; border-bottom: 1px solid rgba(255,255,255,0.035); vertical-align: middle; }}
.fs-admin-table tr:hover td {{ background: rgba(var(--accent-rgb), 0.03); }}
.fs-divider {{ border: none; border-top: 1px solid rgba(255,255,255,0.06); margin: 18px 0; }}
.fs-kb-info-banner {{
    background: rgba(var(--accent-rgb), 0.05);
    border: 1px solid rgba(var(--accent-rgb), 0.18);
    border-radius: 12px;
    padding: 16px 20px;
    margin-bottom: 20px;
}}
.fs-kb-metric-card {{
    background: rgba(14,18,46,0.75);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 16px;
    display: flex;
    align-items: center;
    gap: 14px;
    transition: border-color 0.2s, transform 0.2s;
}}
.fs-kb-metric-card:hover {{
    border-color: var(--border-hover);
    transform: translateY(-2px);
}}
.fs-kb-metric-icon {{
    width: 42px;
    height: 42px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    flex-shrink: 0;
}}
.fs-kb-metric-info {{
    text-align: left;
}}
.fs-kb-progress-wrap {{
    background: rgba(13,17,45,0.45);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 18px 20px;
    margin-bottom: 20px;
}}
.fs-kb-progress-track {{
    background: rgba(255,255,255,0.05);
    border-radius: 99px;
    height: 8px;
    overflow: hidden;
}}
.fs-kb-progress-bar {{
    height: 100%;
    border-radius: 99px;
    transition: width 0.5s ease;
}}
.fs-pdf-text-container {{
    max-height: 500px;
    overflow-y: auto;
    font-size: 14px !important;
}}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)
