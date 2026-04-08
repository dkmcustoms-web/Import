import streamlit as st
import time
import os
from sheets_queue import SheetsQueue
from gmail_sender import GmailSender
from gmail_reader import GmailReader
from code_validator import validate

st.set_page_config(
    page_title="DKM · Commodity Checker",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

for key in [
    "ANTHROPIC_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER",
    "SMTP_PASSWORD","SMTP_FROM","COMMODITY_SHEET_ID",
    "COMMODITY_CC","COMMODITIES_CSV_PATH","GMAIL_SERVICE_ACCOUNT_JSON",
]:
    if key in st.secrets and key not in os.environ:
        os.environ[key] = str(st.secrets[key])

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
[data-testid="stSidebar"]{background:#1a1a2e!important;border-right:2px solid #3cceff33;}
[data-testid="stSidebar"] *{color:#e0e0e0!important;}
.main{background:#0f0f1a;}
.block-container{padding-top:2rem;}
.dkm-header{display:flex;align-items:center;gap:1rem;border-bottom:2px solid #3cceff44;padding-bottom:1rem;margin-bottom:1.5rem;}
.dkm-header h1{font-family:'DM Mono',monospace;font-size:1.6rem;font-weight:500;color:#3cceff;margin:0;}
.dkm-header span{color:#f35e40;}
.metric-card{background:#16213e;border:1px solid #3cceff22;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.6rem;border-left:3px solid var(--accent);}
.metric-card .label{font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:1px;}
.metric-card .value{font-family:'DM Mono',monospace;font-size:1.6rem;color:#fff;margin-top:2px;}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-family:'DM Mono',monospace;font-weight:500;}
.badge-pending{background:#2d2010;color:#f0a500;border:1px solid #f0a50055;}
.badge-flagged{background:#2d1010;color:#f35e40;border:1px solid #f35e4055;}
.badge-sent{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff55;}
.queue-card{background:#16213e;border:1px solid #3cceff22;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:0.8rem;}
.queue-card:hover{border-color:#3cceff66;}
.queue-card .subject{font-weight:600;color:#e0e0e0;font-size:0.95rem;}
.queue-card .meta{font-size:0.78rem;color:#666;margin-top:4px;font-family:'DM Mono',monospace;}
.code-block{background:#0f0f1a;border:1px solid #3cceff33;border-radius:6px;padding:0.6rem 0.9rem;margin-top:0.8rem;font-family:'DM Mono',monospace;font-size:0.85rem;color:#3cceff;}
.ai-verdict{margin-top:0.8rem;padding:0.6rem 0.9rem;border-radius:6px;font-size:0.82rem;line-height:1.5;}
.verdict-found{background:#0d2d1a;border-left:3px solid #2ecc71;color:#b0f0c8;}
.verdict-notfound{background:#2d1010;border-left:3px solid #f35e40;color:#f0b0a0;}
.verdict-ambiguous{background:#2d2010;border-left:3px solid #f0a500;color:#f0d8a0;}
.resolution-tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-family:'DM Mono',monospace;margin-top:6px;}
.res-auto{background:#0d2d1a;color:#2ecc71;border:1px solid #2ecc7133;}
.res-existed{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff33;}
.res-manual{background:#2d2010;color:#f0a500;border:1px solid #f0a50033;}
.res-notfound{background:#2d1010;color:#f35e40;border:1px solid #f35e4033;}
.poll-box{background:#16213e;border:1px solid #3cceff33;border-radius:10px;padding:1rem 1.4rem;margin-bottom:1.5rem;}
@keyframes fadeSlide{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}
.queue-card{animation:fadeSlide 0.3s ease both;}
button[kind="primary"]{background:#f35e40!important;border:none!important;}
hr{border-color:#3cceff22!important;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_queue(): return SheetsQueue()
@st.cache_resource
def get_sender(): return GmailSender()
@st.cache_resource
def get_reader(): return GmailReader()

queue  = get_queue()
sender = get_sender()
reader = get_reader()

@st.cache_data(ttl=30)
def load_items(): return queue.get_all_items()

items = load_items()
total   = len(items)
pending = len([i for i in items if i.get("status") == "pending"])
flagged = len([i for i in items if i.get("status") == "flagged"])
sent    = len([i for i in items if i.get("status") == "sent"])

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Commodity Checker")
    st.markdown("---")

    # Metrics in sidebar
    st.markdown(f"""
    <div class="metric-card" style="--accent:#3cceff">
        <div class="label">Totaal ontvangen</div><div class="value">{total}</div>
    </div>
    <div class="metric-card" style="--accent:#f0a500">
        <div class="label">Wacht op review</div><div class="value">{pending}</div>
    </div>
    <div class="metric-card" style="--accent:#f35e40">
        <div class="label">Geflagd</div><div class="value">{flagged}</div>
    </div>
    <div class="metric-card" style="--accent:#2ecc71">
        <div class="label">Verstuurd</div><div class="value">{sent}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    status_filter = st.selectbox("Filter op status", ["Alle","pending","flagged","sent"], index=0)
    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (60s)", value=False)
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("**DKM Customs**")
    st.markdown("<span style='color:#3cceff;font-size:0.75rem;font-family:monospace'>Commodity Checker v1.0</span>", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="dkm-header"><h1>DKM <span>·</span> Commodity Checker</h1></div>', unsafe_allow_html=True)

# ── Poll sectie ───────────────────────────────────────────────────────────────
st.markdown('<div class="poll-box">', unsafe_allow_html=True)
col1, col2 = st.columns([3,1])
with col1:
    st.markdown("#### 📬 Nieuwe mails ophalen")
    st.markdown("<span style='color:#888;font-size:0.82rem'>Pikt ongelezen mails op met label <b>CommodityCheckAI</b></span>", unsafe_allow_html=True)
with col2:
    check_btn = st.button("📥 Check Gmail nu", type="primary", use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

if check_btn:
    with st.spinner("Gmail controleren…"):
        try:
            new_messages = reader.fetch_new_messages()
            if not new_messages:
                st.info("Geen nieuwe mails gevonden met tag `#commoditycheckAI`.")
            else:
                progress = st.progress(0, text="Valideren…")
                added = 0
                for i, msg in enumerate(new_messages):
                    progress.progress((i+1)/len(new_messages), text=f"Verwerken: {msg['subject'][:50]}")
                    if queue.msg_id_exists(msg["msg_id"]):
                        continue
                    try:
                        result = validate(msg["body"], msg["subject"])
                    except Exception as e:
                        result = {
                            "commodity_code": "ERROR",
                            "code_found": "false",
                            "ai_verdict": f"Validatie mislukt: {e}",
                            "suggested_reply": "Automatic validation failed. A specialist will follow up.",
                            "resolution_type": "error",
                        }
                    status = "flagged" if result["code_found"] == "false" else "pending"
                    queue.add_item({**msg, **result, "status": status})
                    added += 1
                progress.empty()
                if added > 0:
                    st.success(f"✅ {added} nieuwe mail(s) verwerkt!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.info("Mails al eerder verwerkt.")
        except Exception as e:
            st.error(f"Fout: {e}")

# ── Queue ─────────────────────────────────────────────────────────────────────
items = load_items()
if status_filter != "Alle":
    items = [i for i in items if i.get("status") == status_filter]

st.markdown(f"### Queue &nbsp;<span style='font-size:0.85rem;color:#666;font-family:monospace'>({len(items)} items)</span>", unsafe_allow_html=True)

if not items:
    st.info("Geen items in de queue voor dit filter.")
else:
    for item in items:
        row_id         = item.get("row_id")
        status         = item.get("status", "pending")
        subject        = item.get("subject", "(geen subject)")
        sender_mail    = item.get("sender_email", "")
        received_at    = item.get("received_at", "")
        code_asked     = item.get("commodity_code", "")
        ai_result      = item.get("ai_verdict", "")
        ai_found       = str(item.get("code_found","")).lower()
        reply_body     = item.get("suggested_reply","")
        resolution     = item.get("resolution_type","")

        badge_map = {
            "pending": ("badge-pending","⏳ Pending"),
            "flagged": ("badge-flagged","🚩 Geflagd"),
            "sent":    ("badge-sent","📤 Verstuurd"),
        }
        badge_cls, badge_lbl = badge_map.get(status, ("badge-pending", status))
        v_cls = "verdict-found" if ai_found=="true" else ("verdict-ambiguous" if ai_found=="ambiguous" else "verdict-notfound")

        res_tag_map = {
            "auto_resolved": ('<span class="resolution-tag res-auto">🤖 Auto resolved</span>', ),
            "existed":       ('<span class="resolution-tag res-existed">✅ Code existed</span>', ),
            "not_found":     ('<span class="resolution-tag res-notfound">❌ Not found</span>', ),
            "manual":        ('<span class="resolution-tag res-manual">✏️ Manually added</span>', ),
        }
        res_html = res_tag_map.get(resolution, ("",))[0] if resolution else ""

        st.markdown(f"""
        <div class="queue-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <div class="subject">{subject}</div>
                    <div class="meta">✉️ {sender_mail} &nbsp;·&nbsp; 🕐 {received_at}</div>
                    {res_html}
                </div>
                <span class="badge {badge_cls}">{badge_lbl}</span>
            </div>
            <div class="code-block">Commodity code: <strong>{code_asked}</strong></div>
            <div class="ai-verdict {v_cls}"><strong>AI analyse:</strong> {ai_result}</div>
        </div>
        """, unsafe_allow_html=True)

        if status in ("pending","flagged"):
            with st.expander("✏️ Review, manuele code & reply", expanded=(status=="flagged" and ai_found=="false")):

                # Manuele code toevoeging (enkel bij not found)
                if ai_found in ("false",""):
                    st.markdown("**🔎 Code niet gevonden — manueel toevoegen:**")
                    mc1, mc2 = st.columns([1,2])
                    with mc1:
                        manual_code = st.text_input("GN Code", key=f"mcode_{row_id}", placeholder="bijv. 3926909700")
                    with mc2:
                        manual_desc = st.text_input("Omschrijving", key=f"mdesc_{row_id}", placeholder="bijv. Articles of plastics")
                    if st.button("💾 Opslaan in sheet", key=f"msave_{row_id}"):
                        if manual_code:
                            queue.add_manual_code(manual_code, manual_desc)
                            queue.update_status(row_id, status, resolution_type="manual",
                                                manual_code=manual_code, manual_desc=manual_desc)
                            # Update reply met manuele info
                            reply_body = reply_body.replace("[CODE]", manual_code).replace("[DESC]", manual_desc)
                            st.success(f"Code {manual_code} opgeslagen!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.warning("Vul een GN code in.")
                    st.markdown("---")

                edited_reply = st.text_area(
                    "Reply (aanpasbaar voor verzending)",
                    value=reply_body, height=200, key=f"reply_{row_id}",
                )
                c1, c2 = st.columns([1,1])
                with c1:
                    if st.button("📤 Goedkeuren & Versturen", key=f"send_{row_id}", type="primary"):
                        with st.spinner("Versturen…"):
                            ok = sender.send_reply(to=sender_mail, subject=f"Re: {subject}", body=edited_reply)
                            if ok:
                                res_type = "auto_resolved" if ai_found=="true" else ("manual" if ai_found=="false" else "existed")
                                queue.update_status(row_id, "sent", reply_sent=edited_reply, resolution_type=res_type)
                                st.success("✅ Reply verstuurd!")
                                time.sleep(1)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error("❌ Versturen mislukt.")
                with c2:
                    if st.button("🚩 Flaggen", key=f"flag_{row_id}"):
                        queue.update_status(row_id, "flagged")
                        st.warning("Geflagd.")
                        time.sleep(0.8)
                        st.cache_data.clear()
                        st.rerun()
        st.markdown("")

if auto_refresh:
    time.sleep(60)
    st.rerun()
