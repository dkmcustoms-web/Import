# v2.2 - auto-poll Gmail every 10 min
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import time
import os
import re as _re
from sheets_queue import SheetsQueue
from gmail_sender import GmailSender
from gmail_reader import GmailReader
from code_validator import validate

st.set_page_config(page_title="DKM · Commodity Checker", page_icon="🔍", layout="wide")

for key in ["ANTHROPIC_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASSWORD",
            "SMTP_FROM","COMMODITY_SHEET_ID","COMMODITY_CC","COMMODITIES_CSV_PATH","GMAIL_SERVICE_ACCOUNT_JSON"]:
    if key in st.secrets and key not in os.environ:
        os.environ[key] = str(st.secrets[key])

st.markdown("""
<style>
/* Verberg Streamlit toolbar */
header[data-testid="stHeader"] {visibility: hidden; height: 0;}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stToolbar"] {display: none !important;}
.stDeployButton {display: none !important;}
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
[data-testid="stSidebar"]{background:#1a1a2e!important;border-right:2px solid #3cceff33;}
[data-testid="stSidebar"] *{color:#e0e0e0!important;}
.main{background:#0f0f1a;} .block-container{padding-top:2rem;}

.metric-card{background:#16213e;border:1px solid #3cceff22;border-radius:8px;padding:0.8rem 1rem;margin-bottom:0.6rem;border-left:3px solid var(--accent);}
.metric-card .label{font-size:0.7rem;color:#888;text-transform:uppercase;letter-spacing:1px;}
.metric-card .value{font-family:'DM Mono',monospace;font-size:1.6rem;color:#fff;margin-top:2px;}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.72rem;font-family:'DM Mono',monospace;font-weight:500;}
.badge-pending{background:#2d2010;color:#f0a500;border:1px solid #f0a50055;}
.badge-flagged{background:#2d1010;color:#f35e40;border:1px solid #f35e4055;}
.badge-sent{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff55;}
.queue-card{background:#16213e;border:1px solid #3cceff22;border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:0.8rem;}
.queue-card:hover{border-color:#3cceff55;}
.subject{font-weight:600;color:#e0e0e0;font-size:0.95rem;}
.meta{font-size:0.78rem;color:#666;font-family:'DM Mono',monospace;}
.code-block{background:#0f0f1a;border:1px solid #3cceff33;border-radius:6px;padding:0.5rem 0.8rem;font-family:'DM Mono',monospace;font-size:0.85rem;color:#3cceff;white-space:nowrap;}
.ai-verdict{padding:0.6rem 0.9rem;border-radius:6px;font-size:0.82rem;line-height:1.5;}
.verdict-found{background:#0d2d1a;border-left:3px solid #2ecc71;color:#b0f0c8;}
.verdict-notfound{background:#2d1010;border-left:3px solid #f35e40;color:#f0b0a0;}
.verdict-ambiguous{background:#2d2010;border-left:3px solid #f0a500;color:#f0d8a0;}
.resolution-tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-family:'DM Mono',monospace;}
.res-auto{background:#0d2d1a;color:#2ecc71;border:1px solid #2ecc7133;}
.res-existed{background:#0d1a2d;color:#3cceff;border:1px solid #3cceff33;}
.res-manual{background:#2d2010;color:#f0a500;border:1px solid #f0a50033;}
.res-notfound{background:#2d1010;color:#f35e40;border:1px solid #f35e4033;}
.badge-ignored{background:#1a1a2e;color:#555;border:1px solid #55555533;}
.poll-box{background:#16213e;border:1px solid #3cceff33;border-radius:10px;padding:1rem 1.4rem;margin-bottom:1.5rem;}
@keyframes fadeSlide{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
.queue-card{animation:fadeSlide 0.25s ease both;}
button[kind="primary"]{background:#f35e40!important;border:none!important;}
hr{border-color:#3cceff22!important;}
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#16213e;border-radius:8px;padding:4px;}
.stTabs [data-baseweb="tab"]{border-radius:6px;padding:6px 16px;color:#888;}
.stTabs [aria-selected="true"]{background:#3cceff22!important;color:#3cceff!important;}
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

# ── Gmail check functie (gebruikt door manuele knop ÉN auto-poll) ────────────
def run_gmail_check(show_ui=True):
    """Fetch nieuwe mails, valideer, en voeg toe aan queue.
    Returns: aantal verwerkte mails (excl. duplicates)."""
    try:
        new_messages = reader.fetch_new_messages()
        if not new_messages:
            if show_ui:
                st.info("No new emails found with tag `#commoditycheckAI`.")
            return 0

        # Laad learned codes als lookup dict
        try:
            learned_dict = queue.get_learned_lookup()
            if learned_dict:
                print(f"[GmailCheck] Loaded {len(learned_dict)} learned code entries for cache lookup")
        except Exception:
            learned_dict = {}

        progress = st.progress(0, text="Validating…") if show_ui else None
        added = 0
        for i, msg in enumerate(new_messages):
            if progress:
                progress.progress((i+1)/len(new_messages), text=f"Processing: {msg['subject'][:50]}")
            if queue.msg_id_exists(msg["msg_id"]):
                print(f"[GmailCheck] Skip duplicate: {msg['msg_id'][:50]}")
                continue
            try:
                result = validate(msg["body"], msg["subject"], learned_codes=learned_dict)
            except Exception as e:
                result = {"commodity_code":"ERROR","confirmed_code":"","code_found":"false",
                          "ai_verdict":f"Validatie mislukt: {e}",
                          "suggested_reply":"Automatic validation failed. A specialist will follow up.",
                          "resolution_type":"error"}
            status = "flagged" if result["code_found"] == "false" else "pending"
            # Check auto-approve voor cache hits
            auto_sent = False
            if result.get("from_cache") and learned_dict:
                primary = result.get("commodity_code","")
                learned_entry = learned_dict.get(primary, {})
                if str(learned_entry.get("auto_approve","no")).strip().lower() == "yes":
                    # Auto-send zonder menselijke review — voeg AI disclaimer toe
                    base_reply = result.get("suggested_reply","")
                    ai_disclaimer = (
                        "This email is 100% handled by AI, no team member involved. "
                        "If you find something that I did wrong, inform the IT team.\n\n"
                    )
                    reply_text = base_reply.replace(
                        "I checked your question",
                        ai_disclaimer + "I checked your question",
                        1
                    )
                    ok = sender.send_reply(
                        to=msg["sender_email"],
                        subject=f"Re: {msg['subject']}",
                        body=reply_text,
                    )
                    if ok:
                        status = "sent"
                        result["resolution_type"] = "auto_resolved"
                        queue.add_item({**msg, **result, "status": "sent"})
                        conf = learned_entry.get("confirmed_code", primary)
                        queue.learn_code(proposed_code=primary, confirmed_code=conf,
                                         subject=msg["subject"])
                        auto_sent = True
                        print(f"[GmailCheck] Auto-approved and sent for {primary}")

            if not auto_sent:
                queue.add_item({**msg, **result, "status": status})
            added += 1

        if progress:
            progress.empty()

        if added == 0 and show_ui:
            st.info("Emails already processed.")
        return added
    except Exception as e:
        if show_ui:
            st.error(f"Error: {e}")
        print(f"[GmailCheck] Error: {e}")
        return 0

items_all = load_items()
n_queue  = len([i for i in items_all if i.get("status") in ("pending","flagged")])
n_ignored = len([i for i in items_all if i.get("status") == "ignored"])
n_sent   = len([i for i in items_all if i.get("status") == "sent"])
n_total  = len(items_all)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("dkm_logo.png", width=140)
    st.markdown("---")
    st.markdown(f"""
    <div class="metric-card" style="--accent:#f0a500">
        <div class="label">In queue</div><div class="value">{n_queue}</div>
    </div>
    <div class="metric-card" style="--accent:#2ecc71">
        <div class="label">Sent</div><div class="value">{n_sent}</div>
    </div>
    <div class="metric-card" style="--accent:#3cceff">
        <div class="label">Total</div><div class="value">{n_total}</div>
    </div>
    <div class="metric-card" style="--accent:#555">
        <div class="label">Ignored</div><div class="value">{n_ignored}</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    auto_poll = st.toggle(
        "Auto-poll Gmail (10 min)",
        value=True,
        key="auto_poll_gmail",
        help="Checks Gmail automatically every 10 minutes while dashboard is open.",
    )
    st.markdown("---")
    if st.button("⚙️ Confirmations", use_container_width=True):
        st.query_params["page"] = "confirmations"
        st.rerun()
    st.markdown("---")
    learn_setting = st.toggle("Remember confirmed codes", value=True, key="learn_toggle",
        help="Codes are saved after Approve & Send")
    st.session_state["learn_codes"] = learn_setting
    st.markdown("<span style='color:#3cceff;font-size:0.75rem;font-family:monospace'>Commodity Checker v1.0</span>", unsafe_allow_html=True)

# ── Page routing ──────────────────────────────────────────────────────────────
import json as _cjson
_qpage = st.query_params.get("page", "main")

if _qpage == "confirmations":
    # Compacte header op één rij: titel · subtitel · back-knop
    _hc1, _hc2, _hc3 = st.columns([2.2, 3, 1.2])
    with _hc1:
        st.markdown("""<h1 style="font-family:'DM Mono',monospace;font-size:1.3rem;font-weight:500;color:#3cceff;margin:0;padding-top:0.55rem;white-space:nowrap;">DKM <span style="color:#f35e40">·</span> Commodity Checker</h1>""", unsafe_allow_html=True)
    with _hc2:
        st.markdown("""<h2 style="font-family:'DM Sans',sans-serif;font-size:1.15rem;font-weight:500;color:#e0e0e0;margin:0;padding-top:0.6rem;white-space:nowrap;">⚙️ Confirmations <span style="color:#888;font-size:0.9rem;">— Auto-approve</span></h2>""", unsafe_allow_html=True)
    with _hc3:
        if st.button("← Back to Dashboard", use_container_width=True):
            st.query_params.clear()
            st.rerun()
    st.markdown("---")
else:
    # ── Main header ───────────────────────────────────────────────────────────
    st.markdown("""<h1 style="font-family:'DM Mono',monospace;font-size:1.6rem;font-weight:500;color:#3cceff;margin-bottom:1.5rem;">DKM <span style="color:#f35e40">·</span> Commodity Checker</h1>""", unsafe_allow_html=True)

if _qpage == "confirmations":
    st.markdown("<span style='color:#888'>When **ON**, future emails with this code are automatically replied to without manual review.</span>", unsafe_allow_html=True)
    st.markdown("")
    _all_pairs = {}
    try:
        for r in queue.get_learned_codes():
            prop = str(r.get("proposed_code") or r.get("gn_code","")).strip()
            conf = str(r.get("confirmed_code") or r.get("gn_code","")).strip()
            if prop:
                _raw_state = str(r.get("auto_approve","no")).strip().lower()
                if _raw_state not in ("yes", "no", "never"):
                    _raw_state = "no"
                _all_pairs[prop] = {"confirmed":conf,"duty":str(r.get("duty_rate","")).strip(),
                    "times":str(r.get("times_seen",1)),"source":str(r.get("source_subject",""))[:60],
                    "description":"",
                    "auto_approve":_raw_state,"in_learned":True}
    except Exception as _e:
        st.warning(f"Cannot load LearnedCodes: {_e}")
    for _item in [i for i in load_items() if i.get("status")=="sent"]:
        try:
            for _p in _cjson.loads(str(_item.get("display_pairs","")) or "[]"):
                _r=str(_p.get("received","")).strip(); _c=str(_p.get("confirmed","")).strip()
                if _r and _c and _r not in _all_pairs:
                    _all_pairs[_r]={"confirmed":_c,"duty":str(_p.get("duty","")).strip(),
                        "times":"1","source":str(_item.get("subject",""))[:60],
                        "description":str(_p.get("description","")).strip(),
                        "auto_approve":"no","in_learned":False}
        except Exception:
            pass
    if not _all_pairs:
        st.info("No validated codes yet. Approve & Send some replies first.")
    else:
        _approved = {k: v for k, v in _all_pairs.items() if v["auto_approve"] == "yes"}
        _pending  = {k: v for k, v in _all_pairs.items() if v["auto_approve"] == "no"}
        _never    = {k: v for k, v in _all_pairs.items() if v["auto_approve"] == "never"}
        st.markdown(f"**{len(_all_pairs)} validated pair(s)** — 🟢 {len(_approved)} ON · ⭕ {len(_pending)} OFF · 🚫 {len(_never)} NEVER")

        _STATE_LABELS = {"yes": "🟢 Auto", "no": "⭕ Off", "never": "🚫 Never"}
        _LABEL_TO_STATE = {v: k for k, v in _STATE_LABELS.items()}

        def _render_conf_table(pairs_dict, tab_key):
            if not pairs_dict:
                st.info("No entries in this category.")
                return
            _hc=st.columns([1.3,1.3,1.8,0.7,0.5,1.8,1.4])
            for _col,_h in zip(_hc,["Received","Confirmed","Auto-approve","Duty","Times","Description","Source"]):
                _col.markdown(f"<span style='font-size:0.72rem;color:#888;font-family:monospace;text-transform:uppercase;'>{_h}</span>",unsafe_allow_html=True)
            st.markdown("<hr style='margin:4px 0;border-color:#2d3748;'>",unsafe_allow_html=True)
            def _sort_key(kv):
                _prop, _info = kv
                try:
                    _times_n = int(str(_info.get("times", 0)).strip() or 0)
                except ValueError:
                    _times_n = 0
                return (-_times_n, _prop)

            for _prop,_info in sorted(pairs_dict.items(), key=_sort_key):
                _conf=_info["confirmed"]; _duty=_info["duty"]; _times=_info["times"]
                _src=_info["source"]; _state=_info["auto_approve"]; _il=_info["in_learned"]
                _desc=_info.get("description","")
                _cc="#2ecc71" if _prop!=_conf else "#3cceff"
                _rc=st.columns([1.3,1.3,1.8,0.7,0.5,1.8,1.4])
                _rc[0].markdown(f"<span style='font-family:monospace;color:#f0a500;font-size:0.9rem;'>{_prop}</span>",unsafe_allow_html=True)
                _rc[1].markdown(f"<span style='font-family:monospace;color:{_cc};font-weight:700;font-size:0.9rem;'>✅ {_conf}</span>",unsafe_allow_html=True)
                with _rc[2]:
                    _current_label = _STATE_LABELS.get(_state, "⭕ Off")
                    _new_label = st.segmented_control(
                        "auto-approve",
                        options=list(_STATE_LABELS.values()),
                        default=_current_label,
                        key=f"ap_{tab_key}_{_prop}",
                        label_visibility="collapsed",
                    )
                _new_state = _LABEL_TO_STATE.get(_new_label, _state) if _new_label else _state
                _rc[3].markdown(f"<span style='color:#aaa;font-size:0.85rem;'>{_duty}</span>",unsafe_allow_html=True)
                _rc[4].markdown(f"<span style='color:#f0a500;font-weight:600;'>{_times}x</span>",unsafe_allow_html=True)
                _rc[5].markdown(f"<span style='color:#ccc;font-size:0.8rem;font-style:italic;'>{_desc}</span>",unsafe_allow_html=True)
                _rc[6].markdown(f"<span style='color:#555;font-size:0.8rem;'>{_src}</span>",unsafe_allow_html=True)
                if _new_state != _state:
                    if not _il:
                        queue.learn_code(proposed_code=_prop,confirmed_code=_conf,subject=_src,duty_rate=_duty)
                    queue.set_auto_approve(_prop,_new_state)
                    _msg_map = {"yes":"✅ Auto-approve enabled","no":"⭕ Set to manual review","never":"🚫 Never auto-approve"}
                    st.toast(f"{_msg_map.get(_new_state,'Updated')}: {_prop} → {_conf}")
                    st.cache_data.clear()

        _tab_off, _tab_on, _tab_never = st.tabs([
            f"⭕ Auto-approve OFF ({len(_pending)})",
            f"🟢 Auto-approve ON ({len(_approved)})",
            f"🚫 Never ({len(_never)})",
        ])
        with _tab_off:
            _render_conf_table(_pending, "off")
        with _tab_on:
            _render_conf_table(_approved, "on")
        with _tab_never:
            _render_conf_table(_never, "never")
        st.caption("Changes are saved immediately to Google Sheets.")
    st.stop()

# ── Auto-poll trigger (alleen op hoofdpagina) ────────────────────────────────
# st_autorefresh plant elke 10 min een rerun. We pollen alleen wanneer de
# teller daadwerkelijk is opgehoogd — niet bij manuele reruns (knoppen etc.).
if auto_poll:
    _tick = st_autorefresh(interval=600_000, key="gmail_poller")
    if "_last_poll_tick" not in st.session_state:
        # Eerste load: init zonder te pollen, zodat de gebruiker niet meteen
        # een Gmail-call krijgt bij het openen van het dashboard.
        st.session_state["_last_poll_tick"] = _tick
        _should_auto_poll = False
    else:
        _should_auto_poll = _tick > st.session_state["_last_poll_tick"]
        if _should_auto_poll:
            st.session_state["_last_poll_tick"] = _tick
else:
    _should_auto_poll = False

if _should_auto_poll:
    _added = run_gmail_check(show_ui=False)
    if _added > 0:
        st.cache_data.clear()
        st.toast(f"📬 Auto-poll: {_added} new email(s) processed")
        st.rerun()

# ── Poll sectie ────────────────────────────────────────────────────────────────
c1, c2 = st.columns([3,1])
with c1:
    st.markdown("#### 📬 Fetch new emails")
    st.markdown("<span style='color:#888;font-size:0.82rem'>Picks up unread emails with label <b>CommodityCheckAI</b></span>", unsafe_allow_html=True)
with c2:
    check_btn = st.button("📥 Check Gmail now", type="primary", use_container_width=True)
st.markdown("---")

if check_btn:
    with st.spinner("Checking Gmail…"):
        added = run_gmail_check(show_ui=True)
        if added > 0:
            st.success(f"✅ {added} new email(s) processed!")
            st.cache_data.clear(); time.sleep(1); st.rerun()

# ── Render functie ────────────────────────────────────────────────────────────
def render_items(items, allow_actions=True, show_auto_approve=False):
    if not items:
        st.info("No items.")
        return

    for item in items:
        row_id      = item.get("row_id")
        status      = item.get("status","pending")
        subject     = item.get("subject","(geen subject)")
        sender_mail = item.get("sender_email","")
        received_at = item.get("received_at","")
        code_asked  = item.get("commodity_code","")
        ai_result   = item.get("ai_verdict","")
        ai_found    = str(item.get("code_found","")).lower()
        reply_body  = item.get("suggested_reply","")
        resolution  = item.get("resolution_type","")

        badge_map = {"pending":("badge-pending","⏳ Pending"),"flagged":("badge-flagged","🚩 Flagged"),"sent":("badge-sent","📤 Sent"),"ignored":("badge-ignored","🙈 Ignored")}
        badge_cls, badge_lbl = badge_map.get(status, ("badge-pending", status))
        v_cls = "verdict-found" if ai_found=="true" else ("verdict-ambiguous" if ai_found=="ambiguous" else "verdict-notfound")

        from_cache  = str(item.get("from_cache","")).lower() == "true"
        res_map = {"auto_resolved":('<span class="resolution-tag res-auto">' + ('⚡ Cached' if from_cache else '🤖 Auto resolved') + '</span>'),
                   "existed":'<span class="resolution-tag res-existed">✅ Code existed</span>',
                   "not_found":'<span class="resolution-tag res-notfound">❌ Not found</span>',
                   "manual":'<span class="resolution-tag res-manual">✏️ Manually added</span>'}
        res_html = res_map.get(resolution, "")

        # Confirmed code
        confirmed_code = str(item.get("confirmed_code","")).strip()
        if not confirmed_code and str(item.get("manual_code","")).strip():
            confirmed_code = str(item.get("manual_code","")).strip()
        if not confirmed_code and ai_found == "true":
            confirmed_code = code_asked
        if not confirmed_code and ai_result:
            codes_in_text = _re.findall(r"\b\d{10}\b", ai_result)
            for c in codes_in_text:
                if c != code_asked:
                    confirmed_code = c; break
            if not confirmed_code and codes_in_text:
                confirmed_code = codes_in_text[0]
        if not confirmed_code and resolution not in ("not_found","","error"):
            confirmed_code = code_asked

        if confirmed_code:
            confirmed_html = f'<div class="code-block" style="border-color:#2ecc7155;color:#2ecc71;">✅ <strong>{confirmed_code}</strong></div>'
        else:
            confirmed_html = '<div class="code-block" style="border-color:#f35e4055;color:#f35e40;">❓ Niet bevestigd</div>'

        # Gebruik display_pairs uit sheet — exact wat de validator berekende
        import json as _json
        code_asked_str = str(code_asked).strip() if code_asked else ""
        raw_pairs = item.get("display_pairs", "")
        display_pairs = []
        if raw_pairs:
            try:
                display_pairs = _json.loads(str(raw_pairs))
            except Exception:
                pass

        # Fallback als geen display_pairs in sheet
        if not display_pairs:
            conf = str(confirmed_code).strip() if confirmed_code else ""
            display_pairs = [{"received": code_asked_str, "confirmed": conf,
                               "duty": "", "status": "confirmed" if conf else "not_found"}]

        # Bouw HTML rijen — één rij per paar
        status_styles = {
            "confirmed":  ("border-color:#2ecc7155;color:#2ecc71;", "✅"),
            "existed":    ("border-color:#3cceff55;color:#3cceff;", "✅"),
            "not_found":  ("border-color:#f35e4055;color:#f35e40;", "❓"),
        }
        code_rows_parts = []
        for pair in display_pairs:
            received  = pair.get("received", "")
            confirmed = pair.get("confirmed", "")
            pstatus   = pair.get("status", "not_found")
            desc      = pair.get("description", "")
            conf_style, conf_icon = status_styles.get(pstatus, status_styles["not_found"])
            conf_text = confirmed if confirmed else "Not confirmed"
            desc_html = f'<div style="color:#888;font-size:0.78rem;font-style:italic;margin-top:0.2rem;padding-left:2px;">{desc}</div>' if desc else ""
            code_rows_parts.append(
                f'<div style="display:flex;flex-direction:column;margin-top:0.4rem;">' +
                f'<div style="display:flex;gap:0.8rem;align-items:center;">' +
                f'<div class="code-block" style="min-width:150px;">📦 <strong>{received}</strong></div>' +
                f'<div class="code-block" style="{conf_style}min-width:150px;">{conf_icon} <strong>{conf_text}</strong></div>' +
                f'</div>' +
                desc_html +
                f'</div>'
            )
        res_div = f'<div style="margin-top:6px;">{res_html}</div>' if res_html else ""
        code_rows_html = "\n".join(code_rows_parts) + res_div

        st.markdown(f"""
        <div class="queue-card">
            <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
                <div class="subject" style="flex:2;min-width:180px;">{subject}</div>
                <div class="meta" style="flex:1;min-width:120px;">✉️ {sender_mail}</div>
                <div class="meta" style="flex:0 0 auto;white-space:nowrap;">🕐 {received_at}</div>
                <span class="badge {badge_cls}" style="flex:0 0 auto;">{badge_lbl}</span>
            </div>
            {code_rows_html}
            <div class="ai-verdict {v_cls}" style="margin-top:0.8rem;">
                <strong>AI:</strong> {ai_result}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Auto-approve toggle for sent items
        if show_auto_approve and status == "sent":
            import json as _ajson
            raw_dp = item.get("display_pairs","")
            dp = []
            try:
                dp = _ajson.loads(str(raw_dp)) if raw_dp else []
            except Exception:
                pass
            if dp:
                learned_lookup = {}
                try:
                    learned_lookup = queue.get_learned_lookup()
                except Exception:
                    pass
                for pair in dp:
                    p_rec  = str(pair.get("received","")).strip()
                    p_conf = str(pair.get("confirmed","")).strip()
                    if not p_rec or not p_conf:
                        continue
                    entry      = learned_lookup.get(p_rec, {})
                    auto_val   = str(entry.get("auto_approve","no")).strip().lower() == "yes"
                    new_toggle = st.toggle(
                        f"🤖 Auto-approve future emails with `{p_rec}` → `{p_conf}`",
                        value=auto_val,
                        key=f"auto_sent_{row_id}_{p_rec}"
                    )
                    if new_toggle != auto_val:
                        if not entry:
                            # Not yet in learned — add it
                            p_duty = str(pair.get("duty","")).strip()
                            queue.learn_code(proposed_code=p_rec, confirmed_code=p_conf,
                                           subject=subject, duty_rate=p_duty)
                        queue.set_auto_approve(p_rec, new_toggle)
                        st.cache_data.clear()
                        action = "enabled" if new_toggle else "disabled"
                        st.success(f"Auto-approve {action} for {p_rec} → {p_conf}")
                        st.rerun()

        if allow_actions and status in ("pending","flagged"):
            with st.expander("✏️ Review, manual code & reply", expanded=False):
                if ai_found in ("false",""):
                    st.markdown("**🔎 Code not found — add manually:**")
                    mc1, mc2, mc3 = st.columns([1, 1, 2])
                    with mc1:
                        asked_code = st.text_input("Code asked by client", key=f"masked_{row_id}", placeholder="e.g. 3926909700", value=str(code_asked_str))
                    with mc2:
                        manual_code = st.text_input("Correct GN Code", key=f"mcode_{row_id}", placeholder="e.g. 3926909790")
                    with mc3:
                        manual_desc = st.text_input("Description", key=f"mdesc_{row_id}", placeholder="e.g. Articles of plastics, not elsewhere specified")
                    if st.button("💾 Save", key=f"msave_{row_id}"):
                        if manual_code:
                            queue.add_manual_code(manual_code, manual_desc)
                            queue.update_status(row_id, status, resolution_type="manual", manual_code=manual_code, manual_desc=manual_desc)
                            st.success(f"Code {manual_code} saved!")
                            st.cache_data.clear(); st.rerun()
                        else:
                            st.warning("Please enter a GN code.")
                    st.markdown("---")

                # Decision log tonen
                decision_log = item.get("decision_log", "")
                if decision_log:
                    with st.expander("🔍 Decision log", expanded=False):
                        steps = decision_log.split(" | ")
                        for step in steps:
                            if step.strip():
                                color = "#2ecc71" if "EXACT MATCH" in step or "CACHE HIT" in step else ("#f35e40" if "NOT FOUND" in step else "#8899aa")
                                st.markdown(f"<span style='font-family:monospace;font-size:0.8rem;color:{color};'>→ {step.strip()}</span>", unsafe_allow_html=True)

                edited_reply = st.text_area("Reply", value=reply_body, height=180, key=f"reply_{row_id}")
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    if st.button("📤 Approve & Send", key=f"send_{row_id}", type="primary"):
                        with st.spinner("Sending…"):
                            ok = sender.send_reply(to=sender_mail, subject=f"Re: {subject}", body=edited_reply)
                            if ok:
                                res_type = "auto_resolved" if ai_found=="true" else ("manual" if ai_found=="false" else "existed")
                                queue.update_status(row_id, "sent", reply_sent=edited_reply, resolution_type=res_type)
                                # Leer de code als setting aan staat
                                learn = st.session_state.get("learn_codes", True)
                                if learn and res_type in ("auto_resolved","existed"):
                                    # Use display_pairs to save each pair correctly
                                    import json as _ljson
                                    raw_dp = item.get("display_pairs","")
                                    dp = []
                                    try:
                                        dp = _ljson.loads(str(raw_dp)) if raw_dp else []
                                    except Exception:
                                        pass
                                    if dp:
                                        for pair in dp:
                                            p_rec  = str(pair.get("received","")).strip()
                                            p_conf = str(pair.get("confirmed","")).strip()
                                            p_duty = str(pair.get("duty","")).strip()
                                            if p_rec and p_conf:
                                                queue.learn_code(
                                                    proposed_code=p_rec,
                                                    confirmed_code=p_conf,
                                                    subject=subject,
                                                    duty_rate=p_duty,
                                                )
                                        st.success(f"✅ Sent! {len(dp)} code(s) saved to LearnedCodes.")
                                    else:
                                        conf = str(confirmed_code).strip() if confirmed_code else ""
                                        prop = str(code_asked_str).strip() if code_asked_str else ""
                                        if prop and conf:
                                            queue.learn_code(proposed_code=prop, confirmed_code=conf, subject=subject)
                                        st.success("✅ Sent!")
                                else:
                                    st.success("✅ Sent!")
                                st.cache_data.clear(); time.sleep(1); st.rerun()
                            else:
                                st.error("❌ Failed to send.")
                with c2:
                    if st.button("🚩 Flag", key=f"flag_{row_id}"):
                        queue.update_status(row_id, "flagged")
                        st.cache_data.clear(); time.sleep(0.5); st.rerun()
                with c3:
                    if st.button("🙈 Ignore", key=f"ignore_{row_id}"):
                        queue.update_status(row_id, "ignored")
                        st.cache_data.clear(); time.sleep(0.5); st.rerun()
        st.markdown("")

# ── Tabs ──────────────────────────────────────────────────────────────────────
items_all = load_items()
queue_items  = [i for i in items_all if i.get("status") in ("pending","flagged")]
sent_items   = [i for i in items_all if i.get("status") == "sent"]

tab_queue, tab_sent, tab_all = st.tabs([
    f"📋 Queue  ({len(queue_items)})",
    f"📤 Sent  ({len(sent_items)})",
    f"🗂️ All  ({len(items_all)})",
])

with tab_queue:
    render_items(queue_items, allow_actions=True)

with tab_sent:
    render_items(sent_items, allow_actions=False)

with tab_all:
    render_items(items_all, allow_actions=False)
