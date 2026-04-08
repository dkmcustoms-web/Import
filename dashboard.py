import streamlit as st
import pandas as pd
from datetime import datetime
import time
from sheets_queue import SheetsQueue
from gmail_sender import GmailSender

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DKM · Commodity Checker",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brand CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #1a1a2e !important;
    border-right: 2px solid #3cceff33;
}
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
[data-testid="stSidebar"] .stSelectbox label { color: #3cceff !important; }

/* Main area */
.main { background: #0f0f1a; }
.block-container { padding-top: 2rem; }

/* Header */
.dkm-header {
    display: flex; align-items: center; gap: 1rem;
    border-bottom: 2px solid #3cceff44;
    padding-bottom: 1rem; margin-bottom: 1.5rem;
}
.dkm-header h1 {
    font-family: 'DM Mono', monospace;
    font-size: 1.6rem; font-weight: 500;
    color: #3cceff; margin: 0;
    letter-spacing: -0.5px;
}
.dkm-header span { color: #f35e40; }

/* Metric cards */
.metric-row { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
.metric-card {
    flex: 1; background: #16213e;
    border: 1px solid #3cceff22;
    border-radius: 10px; padding: 1rem 1.2rem;
    border-left: 3px solid var(--accent);
}
.metric-card .label { font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }
.metric-card .value { font-family: 'DM Mono', monospace; font-size: 2rem; color: #fff; margin-top: 4px; }

/* Status badges */
.badge {
    display: inline-block; padding: 3px 10px;
    border-radius: 20px; font-size: 0.72rem;
    font-family: 'DM Mono', monospace; font-weight: 500;
}
.badge-pending   { background: #2d2010; color: #f0a500; border: 1px solid #f0a50055; }
.badge-confirmed { background: #0d2d1a; color: #2ecc71; border: 1px solid #2ecc7155; }
.badge-flagged   { background: #2d1010; color: #f35e40; border: 1px solid #f35e4055; }
.badge-sent      { background: #0d1a2d; color: #3cceff; border: 1px solid #3cceff55; }

/* Queue row card */
.queue-card {
    background: #16213e; border: 1px solid #3cceff22;
    border-radius: 10px; padding: 1.2rem 1.4rem;
    margin-bottom: 0.8rem;
    transition: border-color 0.2s;
}
.queue-card:hover { border-color: #3cceff66; }
.queue-card .subject { font-weight: 600; color: #e0e0e0; font-size: 0.95rem; }
.queue-card .meta { font-size: 0.78rem; color: #666; margin-top: 4px; font-family: 'DM Mono', monospace; }
.queue-card .code-block {
    background: #0f0f1a; border: 1px solid #3cceff33;
    border-radius: 6px; padding: 0.6rem 0.9rem;
    margin-top: 0.8rem; font-family: 'DM Mono', monospace;
    font-size: 0.85rem; color: #3cceff;
}
.queue-card .ai-verdict {
    margin-top: 0.8rem; padding: 0.6rem 0.9rem;
    border-radius: 6px; font-size: 0.82rem; line-height: 1.5;
}
.verdict-found    { background: #0d2d1a; border-left: 3px solid #2ecc71; color: #b0f0c8; }
.verdict-notfound { background: #2d1010; border-left: 3px solid #f35e40; color: #f0b0a0; }
.verdict-ambiguous{ background: #2d2010; border-left: 3px solid #f0a500; color: #f0d8a0; }

/* Stagger animation */
@keyframes fadeSlide { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
.queue-card { animation: fadeSlide 0.3s ease both; }

/* Button overrides */
button[kind="primary"] { background: #f35e40 !important; border: none !important; }
button[kind="secondary"] { border-color: #3cceff !important; color: #3cceff !important; }

/* Divider */
hr { border-color: #3cceff22 !important; }

/* Dark inputs */
input, textarea, select { background: #0f0f1a !important; color: #e0e0e0 !important; }
</style>
""", unsafe_allow_html=True)

# ── Init services ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_queue():
    return SheetsQueue()

@st.cache_resource
def get_sender():
    return GmailSender()

queue = get_queue()
sender = get_sender()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Commodity Checker")
    st.markdown("---")
    status_filter = st.selectbox(
        "Filter by status",
        ["All", "pending", "flagged", "confirmed", "sent"],
        index=0,
    )
    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)
    if st.button("🔄 Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("**DKM Customs**")
    st.markdown("Commodity Code Validator")
    st.markdown("<span style='color:#3cceff;font-size:0.75rem;font-family:monospace'>v1.0.0</span>", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="dkm-header">
    <h1>DKM <span>·</span> Commodity Checker</h1>
</div>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_items():
    return queue.get_all_items()

items = load_items()

# ── Metrics ───────────────────────────────────────────────────────────────────
total    = len(items)
pending  = len([i for i in items if i.get("status") == "pending"])
flagged  = len([i for i in items if i.get("status") == "flagged"])
sent     = len([i for i in items if i.get("status") == "sent"])

st.markdown(f"""
<div class="metric-row">
  <div class="metric-card" style="--accent:#3cceff">
    <div class="label">Total received</div>
    <div class="value">{total}</div>
  </div>
  <div class="metric-card" style="--accent:#f0a500">
    <div class="label">Awaiting review</div>
    <div class="value">{pending}</div>
  </div>
  <div class="metric-card" style="--accent:#f35e40">
    <div class="label">Flagged</div>
    <div class="value">{flagged}</div>
  </div>
  <div class="metric-card" style="--accent:#2ecc71">
    <div class="label">Replies sent</div>
    <div class="value">{sent}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Filter ────────────────────────────────────────────────────────────────────
if status_filter != "All":
    items = [i for i in items if i.get("status") == status_filter]

st.markdown(f"### Queue &nbsp;<span style='font-size:0.85rem;color:#666;font-family:monospace'>({len(items)} items)</span>", unsafe_allow_html=True)

if not items:
    st.info("No items in queue matching this filter.")
else:
    for idx, item in enumerate(items):
        row_id      = item.get("row_id")
        status      = item.get("status", "pending")
        subject     = item.get("subject", "(no subject)")
        sender_mail = item.get("sender_email", "")
        received_at = item.get("received_at", "")
        code_asked  = item.get("commodity_code", "")
        ai_result   = item.get("ai_verdict", "")
        ai_found    = item.get("code_found", "").lower()
        reply_body  = item.get("suggested_reply", "")

        # Badge
        badge_map = {
            "pending":   ("badge-pending",   "⏳ Pending"),
            "flagged":   ("badge-flagged",   "🚩 Flagged"),
            "confirmed": ("badge-confirmed", "✅ Confirmed"),
            "sent":      ("badge-sent",      "📤 Sent"),
        }
        badge_cls, badge_lbl = badge_map.get(status, ("badge-pending", status))

        # Verdict class
        v_cls = "verdict-found" if ai_found == "true" else ("verdict-ambiguous" if ai_found == "ambiguous" else "verdict-notfound")

        with st.container():
            st.markdown(f"""
            <div class="queue-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                        <div class="subject">{subject}</div>
                        <div class="meta">✉️ {sender_mail} &nbsp;·&nbsp; 🕐 {received_at}</div>
                    </div>
                    <span class="badge {badge_cls}">{badge_lbl}</span>
                </div>
                <div class="code-block">Commodity code asked: <strong>{code_asked}</strong></div>
                <div class="ai-verdict {v_cls}"><strong>AI Analysis:</strong> {ai_result}</div>
            </div>
            """, unsafe_allow_html=True)

            # Action area (only for actionable statuses)
            if status in ("pending", "flagged"):
                with st.expander("✏️ Review & reply", expanded=False):
                    edited_reply = st.text_area(
                        "Reply message (editable before sending)",
                        value=reply_body,
                        height=160,
                        key=f"reply_{row_id}",
                    )
                    col1, col2, col3 = st.columns([1, 1, 2])
                    with col1:
                        if st.button("📤 Approve & Send", key=f"send_{row_id}", type="primary"):
                            with st.spinner("Sending reply…"):
                                ok = sender.send_reply(
                                    to=sender_mail,
                                    subject=f"Re: {subject}",
                                    body=edited_reply,
                                )
                                if ok:
                                    queue.update_status(row_id, "sent", reply_sent=edited_reply)
                                    st.success("Reply sent!")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error("Failed to send — check Gmail credentials.")
                    with col2:
                        if st.button("🚩 Flag / Skip", key=f"flag_{row_id}"):
                            queue.update_status(row_id, "flagged")
                            st.warning("Flagged for manual handling.")
                            time.sleep(0.8)
                            st.rerun()

            st.markdown("")

# ── Auto refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(30)
    st.rerun()
