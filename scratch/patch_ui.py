import os

ui_path = "app/ui.py"
with open(ui_path, "r", encoding="utf-8") as f:
    content = f.read()

# Verify both markers exist
start_marker = "def inject_global_css(image_path: str):"
end_marker = "def display_paginated_df(df, key_prefix: str"

if start_marker not in content:
    print("Error: start_marker not found")
    exit(1)
if end_marker not in content:
    print("Error: end_marker not found")
    exit(1)

# Split content
parts_before = content.split(start_marker, 1)
before_inject = parts_before[0]
remaining = parts_before[1]

parts_after = remaining.split(end_marker, 1)
after_inject = parts_after[1]

# New inject_global_css definition
new_inject_func = """def inject_global_css(image_path: str, theme_name: str = "Indigo Nebula"):
    encoded = ""
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_f:
            encoded = base64.b64encode(img_f.read()).decode()

    themes = {
        "Indigo Nebula": {
            "primary": "#4F46E5",
            "primary_hover": "#6366F1",
            "secondary": "#7C3AED",
            "secondary_hover": "#8B5CF6",
            "accent_glow": "rgba(79,70,229,0.35)",
            "primary_08": "rgba(79,70,229,0.08)",
            "primary_12": "rgba(79,70,229,0.12)",
            "primary_15": "rgba(79,70,229,0.15)",
            "primary_20": "rgba(79,70,229,0.2)",
            "primary_25": "rgba(79,70,229,0.25)",
            "bg": "linear-gradient(135deg, #060814 0%, #0b112c 60%, #040817 100%)",
            "hero": "linear-gradient(135deg, rgba(49,46,129,0.55) 0%, rgba(76,29,149,0.45) 50%, rgba(30,58,138,0.5) 100%)"
        },
        "Emerald Aurora": {
            "primary": "#0D9488",
            "primary_hover": "#14B8A6",
            "secondary": "#059669",
            "secondary_hover": "#10B981",
            "accent_glow": "rgba(13,148,136,0.35)",
            "primary_08": "rgba(13,148,136,0.08)",
            "primary_12": "rgba(13,148,136,0.12)",
            "primary_15": "rgba(13,148,136,0.15)",
            "primary_20": "rgba(13,148,136,0.2)",
            "primary_25": "rgba(13,148,136,0.25)",
            "bg": "linear-gradient(135deg, #020a07 0%, #051a14 60%, #010c09 100%)",
            "hero": "linear-gradient(135deg, rgba(2,44,34,0.55) 0%, rgba(6,78,59,0.45) 50%, rgba(2,44,34,0.5) 100%)"
        },
        "Nordic Blizzard": {
            "primary": "#0891B2",
            "primary_hover": "#06B6D4",
            "secondary": "#2563EB",
            "secondary_hover": "#3B82F6",
            "accent_glow": "rgba(8,145,178,0.35)",
            "primary_08": "rgba(8,145,178,0.08)",
            "primary_12": "rgba(8,145,178,0.12)",
            "primary_15": "rgba(8,145,178,0.15)",
            "primary_20": "rgba(8,145,178,0.2)",
            "primary_25": "rgba(8,145,178,0.25)",
            "bg": "linear-gradient(135deg, #02070f 0%, #05142a 60%, #010811 100%)",
            "hero": "linear-gradient(135deg, rgba(15,23,42,0.55) 0%, rgba(30,41,59,0.45) 50%, rgba(15,23,42,0.5) 100%)"
        },
        "Crimson Eclipse": {
            "primary": "#E11D48",
            "primary_hover": "#F43F5E",
            "secondary": "#9333EA",
            "secondary_hover": "#A855F7",
            "accent_glow": "rgba(225,29,72,0.35)",
            "primary_08": "rgba(225,29,72,0.08)",
            "primary_12": "rgba(225,29,72,0.12)",
            "primary_15": "rgba(225,29,72,0.15)",
            "primary_20": "rgba(225,29,72,0.2)",
            "primary_25": "rgba(225,29,72,0.25)",
            "bg": "linear-gradient(135deg, #0f0207 0%, #2a0516 60%, #0f0107 100%)",
            "hero": "linear-gradient(135deg, rgba(88,28,135,0.55) 0%, rgba(136,19,55,0.45) 50%, rgba(88,28,135,0.5) 100%)"
        }
    }

    t = themes.get(theme_name, themes["Indigo Nebula"])

    bg_style = (
        f'background: linear-gradient(rgba(8,12,26,0.93), rgba(8,12,26,0.93)), '
        f'url("data:image/jpg;base64,{encoded}") center/cover fixed !important;'
        if encoded
        else "background: var(--bg-grad) !important;"
    )

    css = f\"\"\"
    <style>
    :root {{
        --primary: {t['primary']};
        --primary-hover: {t['primary_hover']};
        --secondary: {t['secondary']};
        --secondary-hover: {t['secondary_hover']};
        --accent-glow: {t['accent_glow']};
        --primary-alpha-08: {t['primary_08']};
        --primary-alpha-12: {t['primary_12']};
        --primary-alpha-15: {t['primary_15']};
        --primary-alpha-20: {t['primary_20']};
        --primary-alpha-25: {t['primary_25']};
        --bg-grad: {t['bg']};
        --hero-grad: {t['hero']};
    }}

    /* ── Google Font ─────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ── Base Reset ─────────────────────────────── */
    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif !important;
        color: #E2E8F0 !important;
    }}

    .stApp {{
        {bg_style}
    }}

    /* ── Scrollbar ───────────────────────────────── */
    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: rgba(255,255,255,0.03); }}
    ::-webkit-scrollbar-thumb {{ background: var(--primary); border-radius: 10px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--primary-hover); }}

    /* ── Sidebar ─────────────────────────────────── */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, rgba(10,13,28,0.97) 0%, rgba(13,18,42,0.97) 100%) !important;
        border-right: 1px solid var(--primary-alpha-15) !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        padding-top: 0 !important;
    }}

    /* ── Main content area padding ──────────────── */
    .block-container {{
        padding: 1.5rem 2rem 2rem 2rem !important;
        max-width: 100% !important;
    }}

    /* ── Typography ─────────────────────────────── */
    .stMarkdown p, .stMarkdown span, .stMarkdown li, .stMarkdown ul {{
        color: #CBD5E1 !important;
        line-height: 1.7 !important;
    }}
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
        color: #F8FAFC !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }}
    .stMarkdown code {{
        font-family: 'JetBrains Mono', monospace !important;
        background: var(--primary-alpha-12) !important;
        color: #A5B4FC !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 0.88em !important;
    }}

    /* ── Labels ─────────────────────────────────── */
    label, .stSelectbox label, .stTextInput label, .stNumberInput label {{
        color: #94A3B8 !important;
        font-weight: 500 !important;
        font-size: 13px !important;
        letter-spacing: 0.02em !important;
        text-transform: uppercase !important;
    }}

    /* ── Input Fields ────────────────────────────── */
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea {{
        background: rgba(15,20,40,0.8) !important;
        color: #F1F5F9 !important;
        border: 1px solid var(--primary-alpha-20) !important;
        border-radius: 8px !important;
        font-family: 'Inter', sans-serif !important;
        transition: border-color 0.2s, box-shadow 0.2s !important;
    }}
    div[data-baseweb="input"]:focus-within,
    div[data-baseweb="textarea"]:focus-within {{
        border-color: var(--primary-hover) !important;
        box-shadow: 0 0 0 3px var(--accent-glow) !important;
    }}

    /* ── Selectbox / Dropdown ────────────────────── */
    div[data-baseweb="select"] > div {{
        background: rgba(15,20,40,0.85) !important;
        border-color: var(--primary-alpha-20) !important;
        color: #F1F5F9 !important;
        border-radius: 8px !important;
    }}
    div[data-baseweb="popover"] {{
        background: #0f1428 !important;
        border: 1px solid var(--primary-alpha-25) !important;
        border-radius: 10px !important;
    }}

    /* ── Buttons ─────────────────────────────────── */
    div.stButton > button,
    form[data-testid="stForm"] button[type="submit"] {{
        background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        letter-spacing: 0.01em !important;
        padding: 0.6rem 1.5rem !important;
        border-radius: 8px !important;
        border: none !important;
        box-shadow: 0 4px 15px var(--accent-glow) !important;
        transition: all 0.25s ease !important;
        width: 100% !important;
    }}
    div.stButton > button:hover,
    form[data-testid="stForm"] button[type="submit"]:hover {{
        background: linear-gradient(135deg, var(--primary-hover) 0%, var(--secondary-hover) 100%) !important;
        box-shadow: 0 6px 22px var(--accent-glow) !important;
        transform: translateY(-1px) !important;
    }}
    div.stButton > button:active {{
        transform: translateY(0) !important;
        box-shadow: 0 2px 8px var(--accent-glow) !important;
    }}

    /* ── Form Container (Login) ──────────────────── */
    form[data-testid="stForm"] {{
        background: rgba(10,14,32,0.85) !important;
        backdrop-filter: blur(32px) !important;
        -webkit-backdrop-filter: blur(32px) !important;
        border: 1px solid var(--primary-alpha-20) !important;
        border-radius: 20px !important;
        padding: 44px 40px !important;
        box-shadow: 0 25px 60px rgba(0,0,0,0.6), 0 0 0 1px var(--primary-alpha-08) !important;
    }}

    /* ── Tabs ────────────────────────────────────── */
    div[data-testid="stTabs"] {{
        background: transparent !important;
    }}
    button[data-baseweb="tab"] {{
        color: #64748B !important;
        font-weight: 500 !important;
        font-size: 14px !important;
        padding: 10px 18px !important;
        border-bottom: 2px solid transparent !important;
        transition: color 0.2s, border-color 0.2s !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: var(--primary-hover) !important;
        font-weight: 700 !important;
        border-bottom-color: var(--primary-hover) !important;
    }}
    button[data-baseweb="tab"]:hover {{
        color: var(--primary-hover) !important;
    }}

    /* ── Expander ────────────────────────────────── */
    div[data-testid="stExpander"] {{
        background: rgba(17,24,50,0.6) !important;
        border: 1px solid var(--primary-alpha-12) !important;
        border-radius: 10px !important;
        margin-top: 8px !important;
    }}
    div[data-testid="stExpander"] summary {{
        color: #94A3B8 !important;
        font-size: 13px !important;
    }}

    /* ── Chat Messages ───────────────────────────── */
    div[data-testid="stChatMessage"] {{
        background: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        padding: 4px 0 !important;
        margin-bottom: 4px !important;
    }}
    /* User bubble */
    div[data-testid="stChatMessage"][data-testid*="user"],
    div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{
        background: var(--primary-alpha-08) !important;
        border: 1px solid var(--primary-alpha-15) !important;
        border-radius: 14px 14px 4px 14px !important;
        padding: 14px 18px !important;
        margin-left: 10% !important;
        margin-bottom: 12px !important;
    }}
    /* Assistant bubble */
    div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {{
        background: rgba(15,21,48,0.7) !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        border-radius: 14px 14px 14px 4px !important;
        padding: 14px 18px !important;
        margin-right: 10% !important;
        margin-bottom: 12px !important;
        backdrop-filter: blur(8px) !important;
    }}
    div[data-testid="stChatMessage"] p,
    div[data-testid="stChatMessage"] li,
    div[data-testid="stChatMessage"] span {{
        color: #E2E8F0 !important;
        font-size: 15px !important;
        line-height: 1.75 !important;
    }}
    div[data-testid="stChatMessage"] code {{
        font-family: 'JetBrains Mono', monospace !important;
        background: var(--primary-alpha-15) !important;
        color: #A5B4FC !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 0.85em !important;
    }}

    /* ── Chat Input Area ─────────────────────────── */
    div[data-testid="stChatInputContainer"] {{
        background: rgba(10,14,32,0.9) !important;
        border: 1px solid var(--primary-alpha-25) !important;
        border-radius: 14px !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3), 0 0 0 1px var(--primary-alpha-12) !important;
        backdrop-filter: blur(12px) !important;
        padding: 4px !important;
        transition: border-color 0.2s, box-shadow 0.2s !important;
    }}
    div[data-testid="stChatInputContainer"]:focus-within {{
        border-color: var(--primary-hover) !important;
        box-shadow: 0 4px 24px var(--accent-glow), 0 0 0 1px var(--primary-hover) !important;
    }}
    textarea[data-testid="stChatInputTextArea"] {{
        background: transparent !important;
        color: #F1F5F9 !important;
        font-size: 15px !important;
        font-family: 'Inter', sans-serif !important;
        border: none !important;
        resize: none !important;
    }}

    /* ── Metric Cards ────────────────────────────── */
    .metric-card {{
        background: linear-gradient(145deg, rgba(16,22,56,0.8) 0%, rgba(12,17,44,0.8) 100%);
        border: 1px solid var(--primary-alpha-15);
        border-radius: 16px;
        padding: 22px 20px;
        text-align: center;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04);
        transition: transform 0.2s, box-shadow 0.2s;
    }}
    .metric-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.35);
    }}
    .metric-label {{
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748B;
        margin-bottom: 10px;
        display: block;
    }}
    .metric-value {{
        font-size: 36px;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1;
    }}

    /* ── Badges ──────────────────────────────────── */
    .badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 6px;
        margin-top: 8px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }}
    .badge-sql {{
        background: rgba(59,130,246,0.12);
        color: #60A5FA;
        border: 1px solid rgba(59,130,246,0.2);
    }}
    .badge-rag {{
        background: var(--primary-alpha-12);
        color: var(--primary-hover);
        border: 1px solid var(--primary-alpha-20);
    }}
    .badge-fallback {{
        background: rgba(245,158,11,0.12);
        color: #FBBF24;
        border: 1px solid rgba(245,158,11,0.2);
    }}

    /* ── Table Styling ───────────────────────────── */
    div[data-testid="stDataFrame"] {{
        border-radius: 10px !important;
        overflow: hidden !important;
        border: 1px solid var(--primary-alpha-12) !important;
    }}
    .table-scroll-container {{
        width: 100% !important;
        max-width: 100% !important;
        overflow-x: auto !important;
        overflow-y: auto !important;
        max-height: 460px !important;
        border-radius: 10px !important;
        border: 1px solid var(--primary-alpha-12) !important;
        background: rgba(10,14,32,0.6) !important;
    }}
    .table-scroll-container table {{
        border-collapse: collapse !important;
        min-width: 100% !important;
        font-size: 13px !important;
        color: #CBD5E1 !important;
        font-family: 'Inter', sans-serif !important;
    }}
    .table-scroll-container th {{
        background: rgba(25,32,72,0.95) !important;
        color: #A5B4FC !important;
        font-weight: 600 !important;
        font-size: 12px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        padding: 10px 14px !important;
        position: sticky !important;
        top: 0 !important;
        border-bottom: 1px solid var(--primary-alpha-20) !important;
        white-space: nowrap !important;
    }}
    .table-scroll-container td {{
        padding: 8px 14px !important;
        border-bottom: 1px solid rgba(255,255,255,0.04) !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        max-width: 220px !important;
    }}
    .table-scroll-container tr:hover td {{
        background: var(--primary-alpha-08) !important;
        color: #F1F5F9 !important;
    }}
    .table-info-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 14px;
        background: rgba(15,20,45,0.5);
        border: 1px solid var(--primary-alpha-08);
        border-top: none;
        border-radius: 0 0 10px 10px;
        font-size: 12px;
        color: #64748B;
        font-family: 'Inter', sans-serif;
    }}

    /* ── File Uploader ───────────────────────────── */
    [data-testid="stFileUploaderDropzone"] {{
        background: rgba(15,20,45,0.5) !important;
        border: 2px dashed var(--primary-alpha-25) !important;
        border-radius: 12px !important;
        transition: border-color 0.2s !important;
    }}
    [data-testid="stFileUploaderDropzone"]:hover {{
        border-color: var(--primary-hover) !important;
    }}

    /* ── Alert / Info ────────────────────────────── */
    div[data-testid="stAlert"] {{
        border-radius: 10px !important;
        border-left-width: 3px !important;
    }}

    /* ── Spinner / Thinking Dots ─────────────────── */
    .thinking-dot {{
        display: inline-block;
        width: 7px; height: 7px;
        margin: 0 3px;
        background: var(--primary-hover);
        border-radius: 50%;
        animation: thinking-bounce 1.3s infinite ease-in-out;
    }}
    .thinking-dot:nth-child(2) {{ animation-delay: 0.2s; }}
    .thinking-dot:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes thinking-bounce {{
        0%, 80%, 100% {{ transform: scale(0.7); opacity: 0.4; }}
        40% {{ transform: scale(1.2); opacity: 1; }}
    }}

    /* ── Chat Layout: messages scroll area ──────── */
    .chat-messages-area {{
        overflow-y: auto;
        padding-bottom: 16px;
    }}

    /* ── Access Denied Banner ───────────────────── */
    .access-denied-box {{
        background: linear-gradient(135deg, rgba(239,68,68,0.08) 0%, rgba(220,38,38,0.06) 100%);
        border: 1px solid rgba(239,68,68,0.25);
        border-left: 3px solid #EF4444;
        border-radius: 10px;
        padding: 16px 20px;
        margin: 4px 0;
    }}
    .access-denied-box .ad-title {{
        font-size: 14px;
        font-weight: 700;
        color: #FCA5A5;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .access-denied-box .ad-body {{
        font-size: 13px;
        color: #94A3B8;
        line-height: 1.6;
    }}

    /* ── Hero Banner ─────────────────────────────── */
    .hero-banner {{
        background: var(--hero-grad) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid var(--primary-alpha-20) !important;
        border-radius: 18px;
        padding: 28px 36px;
        margin-bottom: 28px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.06);
        display: flex;
        align-items: center;
        gap: 20px;
    }}
    .hero-icon {{ font-size: 42px; line-height: 1; flex-shrink: 0; }}
    .hero-title {{
        font-size: 24px !important;
        font-weight: 800 !important;
        color: #FFFFFF !important;
        letter-spacing: -0.025em;
        margin: 0 0 4px 0;
        line-height: 1.2;
    }}
    .hero-subtitle {{
        color: #94A3B8 !important;
        font-size: 14px !important;
        margin: 0;
        font-weight: 400;
    }}

    /* ── Status Dot ──────────────────────────────── */
    .status-online {{
        display: inline-block;
        width: 8px; height: 8px;
        background: #10B981;
        border-radius: 50%;
        box-shadow: 0 0 6px #10B981;
        animation: pulse-green 2s infinite;
    }}
    @keyframes pulse-green {{
        0%, 100% {{ box-shadow: 0 0 4px #10B981; }}
        50% {{ box-shadow: 0 0 12px #10B981, 0 0 20px rgba(16,185,129,0.3); }}
    }}

    /* ── Section Cards ───────────────────────────── */
    .section-card {{
        background: rgba(13,17,45,0.7);
        border: 1px solid var(--primary-alpha-12);
        border-radius: 14px;
        padding: 22px 24px;
        margin-bottom: 20px;
        backdrop-filter: blur(8px);
    }}
    .section-title {{
        font-size: 16px;
        font-weight: 700;
        color: #F1F5F9 !important;
        margin: 0 0 4px 0;
    }}
    .section-subtitle {{
        font-size: 13px;
        color: #64748B !important;
        margin: 0 0 18px 0;
    }}

    /* ── Number Input ────────────────────────────── */
    div[data-testid="stNumberInput"] input {{
        background: rgba(15,20,40,0.8) !important;
        color: #F1F5F9 !important;
        border: 1px solid var(--primary-alpha-20) !important;
        border-radius: 8px !important;
    }}
    </style>
    \"\"\"
    st.markdown(css, unsafe_allow_html=True)
"""

# Replace in content
replaced_content = before_inject + new_inject_func + "\\n\\n" + end_marker + after_inject

# Also modify session state init loop
session_init_old = """for key, default in [
    ("auth", None), ("role", None), ("page", "login"),
    ("messages", []), ("username", ""), ("roles", []),
]:"""

session_init_new = """for key, default in [
    ("auth", None), ("role", None), ("page", "login"),
    ("messages", []), ("username", ""), ("roles", []),
    ("theme", "Indigo Nebula"),
]:"""

if session_init_old in replaced_content:
    replaced_content = replaced_content.replace(session_init_old, session_init_new)
else:
    print("Warning: session_init_old not found")

# Inject theme call after the init loop
init_loop_end = """    if key not in st.session_state:
        st.session_state[key] = default"""

init_loop_new = """    if key not in st.session_state:
        st.session_state[key] = default

inject_global_css(os.path.join(BASE_DIR, "static", "images", "background.jpg"), st.session_state.theme)"""

if init_loop_end in replaced_content:
    # We only want to replace the first occurrence (which is right after session state init loop)
    replaced_content = replaced_content.replace(init_loop_end, init_loop_new, 1)
else:
    print("Warning: init_loop_end not found")

with open(ui_path, "w", encoding="utf-8") as f:
    f.write(replaced_content)

print("ui.py patched successfully!")
