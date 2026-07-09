"""
app/ui/pages/kb_indexing.py — Knowledge Base Indexing status & controls.

Extracted from the Admin tab so indexing has its own dedicated space
with clearer metrics, document table, and action buttons.
"""

import time

import requests
import streamlit as st

from app.ui.constants import API_URL, ROLE_COLORS
from app.ui.helpers import api_headers, fetch_bulk_status


def render_kb_indexing_tab() -> None:
    """Render the Knowledge Base Indexing status tab (C-Level only)."""

    # ── Section header ────────────────────────────────────────────────────────
    st.markdown(
        '<div class="fs-section">'
        '<div class="fs-section-title">🗂️ Knowledge Base — Indexing Status</div>'
        '<div class="fs-section-sub">Monitor, retry, and manage the document indexing pipeline in real time.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Info banner ───────────────────────────────────────────────────────────
    st.markdown("""
    <div class="fs-kb-info-banner">
        <div style="display:flex;align-items:flex-start;gap:12px;">
            <span style="font-size:20px;flex-shrink:0;margin-top:1px;">💡</span>
            <div>
                <div style="font-weight:700;font-size:13.5px;color:#F8FAFC;margin-bottom:4px;">
                    How indexing works
                </div>
                <div style="font-size:12px;color:#94A3B8;line-height:1.6;">
                    Documents are split into chunks and embedded into the vector store for RAG retrieval.
                    Use <b>Retry failed/pending</b> to resume after a quota error without re-embedding
                    already-indexed docs. Use <b>Re-index all</b> to wipe and rebuild from scratch.
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Fetch status data ─────────────────────────────────────────────────────
    bulk_data = fetch_bulk_status()
    summary   = bulk_data.get("summary", {}) if bulk_data else {}
    all_docs  = bulk_data.get("documents", []) if bulk_data else []

    total   = summary.get("total",   0)
    done    = summary.get("done",    0)
    failed  = summary.get("failed",  0)
    pending = summary.get("pending", 0)
    pct     = int(done / total * 100) if total > 0 else 0

    # ── Summary metric cards ──────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    for col, (label, val, color, icon) in zip(
        [m1, m2, m3, m4],
        [("Total Docs",  total,   "#818CF8", "📁"),
         ("Indexed",     done,    "#10B981", "✅"),
         ("Pending",     pending, "#F59E0B", "⏳"),
         ("Failed",      failed,  "#EF4444", "❌")],
    ):
        with col:
            st.markdown(
                f'<div class="fs-kb-metric-card">'
                f'<div class="fs-kb-metric-icon" style="background:rgba({_hex_to_rgb(color)},0.12);'
                f'color:{color};">{icon}</div>'
                f'<div class="fs-kb-metric-info">'
                f'<span class="fs-metric-label">{label}</span>'
                f'<div class="fs-metric-value" style="color:{color};">{val}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    # ── Overall progress bar ──────────────────────────────────────────────────
    if pending > 0:
        bar_color = "linear-gradient(90deg, var(--primary), var(--secondary))"
        bar_label = f"🔄 Indexing in progress… {done}/{total} done ({pct}%)"
    elif done == total and total > 0 and failed == 0:
        bar_color = "#10B981"
        bar_label = f"✅ All {total} documents indexed successfully"
    elif failed > 0 and pending == 0:
        bar_color = "#EF4444"
        bar_label = f"⚠️ {done} indexed · {failed} failed — click Retry below"
    else:
        bar_color = "#475569"
        bar_label = "No documents — upload files from the Upload tab"

    st.markdown(f"""
    <div class="fs-kb-progress-wrap">
        <div style="font-size:12.5px;color:var(--text-secondary);margin-bottom:6px;font-weight:500;">
            {bar_label}
        </div>
        <div class="fs-kb-progress-track">
            <div class="fs-kb-progress-bar" style="width:{pct}%;background:{bar_color};"></div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-top:5px;">
            <span style="font-size:10.5px;color:var(--text-muted);">0%</span>
            <span style="font-size:10.5px;color:var(--text-muted);font-weight:600;">{pct}%</span>
            <span style="font-size:10.5px;color:var(--text-muted);">100%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Auto-refresh while indexing ───────────────────────────────────────────
    if pending > 0:
        st.caption("🔄 Auto-refreshing every 5 seconds while indexing…")
        time.sleep(5)
        st.rerun()

    # ── Action buttons ────────────────────────────────────────────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    btn1, btn2, btn3, _ = st.columns([1.8, 1.8, 1.2, 1])
    with btn1:
        do_retry = st.button("🔁 Retry failed / pending", key="kb_retry",
                             help="Re-runs indexing for failed/pending only.")
    with btn2:
        do_reindex = st.button("🔄 Re-index all (wipe & rebuild)", key="kb_reindex",
                               help="⚠️ Destructive: wipes vector store and re-embeds everything.")
    with btn3:
        if st.button("🔃 Refresh", key="kb_refresh"):
            st.rerun()

    if do_retry:
        with st.spinner("Resetting failed docs and starting retry…"):
            try:
                r = requests.post(f"{API_URL}/reindex-retry", headers=api_headers(), timeout=15)
                if r.ok:
                    st.success("🔁 Retry started — failed/pending docs re-queued.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(r.json().get("detail", "Retry failed."))
            except Exception as exc:
                st.error(f"Error: {exc}")

    if do_reindex:
        if not st.session_state.get("_reindex_confirm"):
            st.session_state["_reindex_confirm"] = True
            st.warning(
                "⚠️ **Confirm full re-index** — this wipes ALL embeddings and re-processes "
                "every document from scratch. Click **Re-index all** again to confirm."
            )
        else:
            st.session_state.pop("_reindex_confirm", None)
            with st.spinner("Wiping vector store and starting re-index…"):
                try:
                    r = requests.post(f"{API_URL}/reindex", headers=api_headers(), timeout=30)
                    if r.ok:
                        st.success("🎉 Full re-index started! All documents queued for re-embedding.")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(r.json().get("detail", "Failed."))
                except Exception as exc:
                    st.error(f"Error: {exc}")

    # ── Per-document table ────────────────────────────────────────────────────
    st.markdown('<hr class="fs-divider">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-weight:700;font-size:14px;color:#F1F5F9;margin-bottom:12px;">'
        '📋 Document Indexing Details</div>',
        unsafe_allow_html=True,
    )

    filter_col, search_col, _ = st.columns([1.5, 2, 1.5])
    with filter_col:
        status_filter = st.selectbox(
            "Filter", ["All", "✅ Indexed", "⏳ Pending", "❌ Failed"],
            key="kb_filter", label_visibility="collapsed",
        )
    with search_col:
        search_term = st.text_input(
            "Search", key="kb_search", placeholder="🔍 Search documents…",
            label_visibility="collapsed",
        )

    filter_map = {"✅ Indexed": "indexed", "⏳ Pending": "pending", "❌ Failed": "failed"}
    docs = [
        d for d in all_docs
        if (status_filter == "All" or d["status"] == filter_map.get(status_filter))
        and (not search_term or search_term.lower() in d["filename"].lower())
    ]

    if not docs:
        st.info(
            "No documents match this filter."
            if status_filter != "All" or search_term
            else "No documents ingested yet. Upload files from the Upload tab."
        )
    else:
        status_badge = {
            "indexed": '<span style="background:#064E3B;color:#6EE7B7;border-radius:5px;'
                       'padding:2px 8px;font-size:11px;font-weight:700;">✅ Indexed</span>',
            "pending": '<span style="background:#451A03;color:#FCD34D;border-radius:5px;'
                       'padding:2px 8px;font-size:11px;font-weight:700;">⏳ Pending</span>',
            "failed":  '<span style="background:#450A0A;color:#FCA5A5;border-radius:5px;'
                       'padding:2px 8px;font-size:11px;font-weight:700;">❌ Failed</span>',
            "unknown": '<span style="background:#1E293B;color:#94A3B8;border-radius:5px;'
                       'padding:2px 8px;font-size:11px;">❓ Unknown</span>',
        }
        rows_html = ""
        for doc in docs:
            badge   = status_badge.get(doc["status"], status_badge["unknown"])
            tc, ec  = doc["total_chunks"], doc["embedded_chunks"]
            prog    = f"{ec}/{tc}" if tc > 0 else "—"
            bar_pct = int(ec / tc * 100) if tc > 0 else 0
            bar_c   = (
                "#10B981" if doc["status"] == "indexed"
                else "#F59E0B" if doc["status"] == "pending"
                else "#EF4444"
            )
            rc2 = ROLE_COLORS.get(doc["role"], "#6366F1")
            rows_html += f"""
            <tr>
                <td title="{doc['filename']}" style="color:#E2E8F0;max-width:220px;
                    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                    {doc['filename']}
                </td>
                <td><span style="color:{rc2};font-weight:600;font-size:12px;">{doc['role']}</span></td>
                <td>{badge}</td>
                <td style="min-width:120px;">
                    <div style="font-size:11px;color:var(--text-muted);margin-bottom:3px;">{prog} chunks</div>
                    <div style="background:rgba(255,255,255,0.05);border-radius:99px;height:4px;overflow:hidden;">
                        <div style="width:{bar_pct}%;background:{bar_c};height:100%;
                            border-radius:99px;transition:width 0.4s ease;"></div>
                    </div>
                </td>
            </tr>"""

        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.01);border:1px solid rgba(255,255,255,0.06);
            border-radius:10px;overflow:hidden;margin-bottom:18px;">
            <table class="fs-admin-table">
                <thead><tr>
                    <th>Document</th><th>Role</th><th>Status</th><th>Chunk Progress</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>""", unsafe_allow_html=True)

        # Document count footer
        st.markdown(
            f'<div style="text-align:right;font-size:11px;color:var(--text-muted);margin-top:-12px;">'
            f'Showing {len(docs)} of {len(all_docs)} documents</div>',
            unsafe_allow_html=True,
        )


def _hex_to_rgb(hex_color: str) -> str:
    """Convert '#RRGGBB' to 'R,G,B' for use in rgba()."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"
