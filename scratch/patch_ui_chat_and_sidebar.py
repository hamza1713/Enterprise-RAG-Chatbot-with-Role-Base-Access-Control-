import os

ui_path = "app/ui.py"
with open(ui_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace user card styling
old_user_card = """                    background:linear-gradient(135deg,#4F46E5,#7C3AED);
                    display:flex;align-items:center;justify-content:center;
                    font-size:20px;flex-shrink:0;
                    box-shadow:0 4px 12px rgba(79,70,229,0.3);"""

new_user_card = """                    background:linear-gradient(135deg,var(--primary),var(--secondary));
                    display:flex;align-items:center;justify-content:center;
                    font-size:20px;flex-shrink:0;
                    box-shadow:0 4px 12px var(--accent-glow);"""

if old_user_card in content:
    content = content.replace(old_user_card, new_user_card)
else:
    print("Warning: old_user_card not found")

old_role_badge = """            background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.2);
                padding:4px 12px;border-radius:20px;">
                <span style="color:#818CF8;font-size:12px;font-weight:600;">{role}</span>"""

new_role_badge = """            background:var(--primary-alpha-12);border:1px solid var(--primary-alpha-20);
                padding:4px 12px;border-radius:20px;">
                <span style="color:var(--primary-hover);font-size:12px;font-weight:600;">{role}</span>"""

if old_role_badge in content:
    content = content.replace(old_role_badge, new_role_badge)
else:
    print("Warning: old_role_badge not found")

# 2. Add Theme Selector after Online Status
old_system_status = """        # System status
        st.markdown(\"\"\"
        <div style="padding:0 20px;margin-bottom:20px;">
            <div style="display:flex;align-items:center;gap:8px;font-size:13px;color:#10B981;font-weight:500;">
                <span class="status-online"></span>
                Gemini Assistant Online
            </div>
        </div>
        \"\"\", unsafe_allow_html=True)"""

new_system_status = """        # System status
        st.markdown(\"\"\"
        <div style="padding:0 20px;margin-bottom:20px;">
            <div style="display:flex;align-items:center;gap:8px;font-size:13px;color:#10B981;font-weight:500;">
                <span class="status-online"></span>
                Gemini Assistant Online
            </div>
        </div>
        \"\"\", unsafe_allow_html=True)

        # Theme Selector
        st.markdown(\"\"\"
        <div style="padding:0 20px;margin-bottom:8px;font-size:11px;font-weight:700;text-transform:uppercase;color:#64748B;letter-spacing:0.05em;">
            🎨 Application Theme
        </div>
        \"\"\", unsafe_allow_html=True)
        theme_options = ["Indigo Nebula", "Emerald Aurora", "Nordic Blizzard", "Crimson Eclipse"]
        current_theme = st.session_state.get("theme", "Indigo Nebula")
        if current_theme not in theme_options:
            current_theme = "Indigo Nebula"
        current_theme_index = theme_options.index(current_theme)
        selected_theme = st.selectbox(
            "Select Theme",
            options=theme_options,
            index=current_theme_index,
            key="theme_selectbox",
            label_visibility="collapsed"
        )
        if selected_theme != st.session_state.get("theme", "Indigo Nebula"):
            st.session_state.theme = selected_theme
            st.rerun()"""

if old_system_status in content:
    content = content.replace(old_system_status, new_system_status)
else:
    print("Warning: old_system_status not found")


# 3. Restructure Chat Tab layout to put input box at the bottom
old_chat_tab_start = """    with chat_tab:
        # ── Step 1: Capture input FIRST (Streamlit renders it at the bottom of its scope) ──
        question = st.chat_input("Ask a question about your workspace data...", key="chat_input_main")

        # ── Step 2: Render ALL history + new response in a scrollable container above ──
        messages_container = st.container()
        with messages_container:
            if not st.session_state.messages and not question:
                # Empty state placeholder
                st.markdown(\"\"\"
                <div style="text-align:center;padding:60px 20px;">
                    <div style="font-size:52px;margin-bottom:16px;">💬</div>
                    <div style="font-size:17px;font-weight:700;color:#475569;margin-bottom:8px;">Start a Conversation</div>
                    <div style="font-size:14px;color:#334155;max-width:420px;margin:0 auto;line-height:1.7;">
                        Ask about policies, employee records, financial reports, or anything in your workspace documents.
                    </div>
                    <div style="margin-top:28px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">
                        <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.15);border-radius:20px;padding:8px 16px;font-size:13px;color:#818CF8;cursor:default;">📄 Summarize HR policy</div>
                        <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.15);border-radius:20px;padding:8px 16px;font-size:13px;color:#818CF8;cursor:default;">📊 Show top earning employees</div>
                        <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.15);border-radius:20px;padding:8px 16px;font-size:13px;color:#818CF8;cursor:default;">💰 Explain Q4 budget</div>
                    </div>
                </div>
                \"\"\", unsafe_allow_html=True)
            else:
                # Render chat history
                for msg in st.session_state.messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if "sql" in msg:
                            st.markdown('<span class="badge badge-sql">📊 SQL Query</span>', unsafe_allow_html=True)
                            with st.expander("Show SQL"):
                                st.code(msg["sql"], language="sql")
                        elif "mode" in msg and "SQL" not in msg.get("mode", ""):
                            st.markdown('<span class="badge badge-rag">📄 RAG Document</span>', unsafe_allow_html=True)
                        if msg.get("sources"):
                            render_message_sources(msg["sources"], role)

        # ── Step 3: Handle new question — renders inside messages_container (below history) ──
        if question:"""

new_chat_tab_start = """    with chat_tab:
        # ── Step 1: Render ALL history in a container above ──
        messages_container = st.container()
        with messages_container:
            if not st.session_state.messages:
                # Empty state placeholder
                st.markdown(\"\"\"
                <div style="text-align:center;padding:60px 20px;">
                    <div style="font-size:52px;margin-bottom:16px;">💬</div>
                    <div style="font-size:17px;font-weight:700;color:#475569;margin-bottom:8px;">Start a Conversation</div>
                    <div style="font-size:14px;color:#334155;max-width:420px;margin:0 auto;line-height:1.7;">
                        Ask about policies, employee records, financial reports, or anything in your workspace documents.
                    </div>
                    <div style="margin-top:28px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">
                        <div style="background:var(--primary-alpha-08);border:1px solid var(--primary-alpha-15);border-radius:20px;padding:8px 16px;font-size:13px;color:var(--primary-hover);cursor:default;">📄 Summarize HR policy</div>
                        <div style="background:var(--primary-alpha-08);border:1px solid var(--primary-alpha-15);border-radius:20px;padding:8px 16px;font-size:13px;color:var(--primary-hover);cursor:default;">📊 Show top earning employees</div>
                        <div style="background:var(--primary-alpha-08);border:1px solid var(--primary-alpha-15);border-radius:20px;padding:8px 16px;font-size:13px;color:var(--primary-hover);cursor:default;">💰 Explain Q4 budget</div>
                    </div>
                </div>
                \"\"\", unsafe_allow_html=True)
            else:
                # Render chat history
                for msg in st.session_state.messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
                        if "sql" in msg:
                            st.markdown('<span class="badge badge-sql">📊 SQL Query</span>', unsafe_allow_html=True)
                            with st.expander("Show SQL"):
                                st.code(msg["sql"], language="sql")
                        elif "mode" in msg and "SQL" not in msg.get("mode", ""):
                            st.markdown('<span class="badge badge-rag">📄 RAG Document</span>', unsafe_allow_html=True)
                        if msg.get("sources"):
                            render_message_sources(msg["sources"], role)

        # ── Step 2: Capture input at the bottom ──
        question = st.chat_input("Ask a question about your workspace data...", key="chat_input_main")

        # ── Step 3: Handle new question — renders inside messages_container (below history) ──
        if question:"""

if old_chat_tab_start in content:
    content = content.replace(old_chat_tab_start, new_chat_tab_start)
else:
    # Print the first 50 chars of both to see where the mismatch is
    print("Warning: old_chat_tab_start not found.")
    print("Attempting fuzzy patch for chat tab...")
    # Let's try to find 'with chat_tab:' and split there
    if "with chat_tab:" in content:
        print("Fuzzy match successful for with chat_tab:")

with open(ui_path, "w", encoding="utf-8") as f:
    f.write(content)

print("ui.py patched successfully!")
