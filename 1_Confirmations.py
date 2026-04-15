import streamlit as st
import os
import json

st.set_page_config(page_title="DKM · Confirmations", page_icon="⚙️", layout="wide")

for key in ["ANTHROPIC_API_KEY","SMTP_HOST","SMTP_PORT","SMTP_USER","SMTP_PASSWORD",
            "SMTP_FROM","COMMODITY_SHEET_ID","COMMODITY_CC","COMMODITIES_CSV_PATH","GMAIL_SERVICE_ACCOUNT_JSON"]:
    if key in st.secrets and key not in os.environ:
        os.environ[key] = str(st.secrets[key])

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
[data-testid="stSidebar"]{background:#1a1a2e!important;border-right:2px solid #3cceff33;}
[data-testid="stSidebar"] *{color:#e0e0e0!important;}
header[data-testid="stHeader"]{visibility:hidden;height:0;}
#MainMenu{visibility:hidden;} footer{visibility:hidden;}
[data-testid="stToolbar"]{display:none!important;}
</style>
""", unsafe_allow_html=True)

import sys
sys.path.insert(0, "/mount/src/import")
from sheets_queue import SheetsQueue

@st.cache_resource
def get_queue(): return SheetsQueue()
queue = get_queue()

@st.cache_data(ttl=30)
def load_items(): return queue.get_all_items()

# Header with back button
col_back, col_title = st.columns([1, 6])
with col_back:
    if st.button("← Dashboard"):
        st.switch_page("dashboard.py")
with col_title:
    st.markdown('<h2 style="font-family:\'DM Mono\',monospace;color:#3cceff;margin:0;">⚙️ Confirmations <span style="color:#f35e40;font-size:1rem;">— Auto-approve</span></h2>', unsafe_allow_html=True)

st.markdown("---")
st.markdown("<span style='color:#888'>When **ON**, future emails with this code are automatically replied to without manual review.</span>", unsafe_allow_html=True)
st.markdown("")

all_pairs = {}
try:
    for r in queue.get_learned_codes():
        prop = str(r.get("proposed_code") or r.get("gn_code","")).strip()
        conf = str(r.get("confirmed_code") or r.get("gn_code","")).strip()
        if prop:
            all_pairs[prop] = {
                "confirmed":   conf, "duty": str(r.get("duty_rate","")).strip(),
                "times":       str(r.get("times_seen",1)), "source": str(r.get("source_subject",""))[:60],
                "auto_approve":str(r.get("auto_approve","no")).strip().lower()=="yes", "in_learned":True,
            }
except Exception as e:
    st.warning(f"Cannot load LearnedCodes: {e}")

for item in [i for i in load_items() if i.get("status")=="sent"]:
    try:
        for pair in json.loads(str(item.get("display_pairs","")) or "[]"):
            p_r=str(pair.get("received","")).strip(); p_c=str(pair.get("confirmed","")).strip()
            if p_r and p_c and p_r not in all_pairs:
                all_pairs[p_r]={"confirmed":p_c,"duty":str(pair.get("duty","")).strip(),
                    "times":"1","source":str(item.get("subject",""))[:60],"auto_approve":False,"in_learned":False}
    except Exception:
        pass

if not all_pairs:
    st.info("No validated codes yet. Approve & Send some replies first.")
else:
    approved  = {k: v for k, v in all_pairs.items() if v["auto_approve"]}
    pending   = {k: v for k, v in all_pairs.items() if not v["auto_approve"]}

    st.markdown(f"**{len(all_pairs)} validated pair(s)** — 🟢 {len(approved)} auto-approve ON · ⭕ {len(pending)} OFF")

    def render_table(pairs_dict, tab_key):
        if not pairs_dict:
            st.info("No entries in this category.")
            return
        hcols = st.columns([1.4,1.4,0.8,0.5,3,1.4])
        for col,h in zip(hcols,["Received","Confirmed","Duty","Times","Source","Auto-approve"]):
            col.markdown(f"<span style='font-size:0.72rem;color:#888;font-family:monospace;text-transform:uppercase;'>{h}</span>",unsafe_allow_html=True)
        st.markdown("<hr style='margin:4px 0;border-color:#2d3748;'>",unsafe_allow_html=True)
        for prop, info in sorted(pairs_dict.items()):
            conf=info["confirmed"]; duty=info["duty"]; times=info["times"]
            source=info["source"]; av=info["auto_approve"]; il=info["in_learned"]
            cc="#2ecc71" if prop!=conf else "#3cceff"
            rc=st.columns([1.4,1.4,0.8,0.5,3,1.4])
            rc[0].markdown(f"<span style='font-family:monospace;color:#f0a500;font-size:0.9rem;'>{prop}</span>",unsafe_allow_html=True)
            rc[1].markdown(f"<span style='font-family:monospace;color:{cc};font-weight:700;font-size:0.9rem;'>✅ {conf}</span>",unsafe_allow_html=True)
            rc[2].markdown(f"<span style='color:#aaa;font-size:0.85rem;'>{duty}</span>",unsafe_allow_html=True)
            rc[3].markdown(f"<span style='color:#f0a500;font-weight:600;'>{times}x</span>",unsafe_allow_html=True)
            rc[4].markdown(f"<span style='color:#555;font-size:0.8rem;'>{source}</span>",unsafe_allow_html=True)
            nv=rc[5].toggle("",value=av,key=f"ap_{tab_key}_{prop}",label_visibility="collapsed",help=f"{prop}→{conf}")
            if nv != av:
                if not il:
                    queue.learn_code(proposed_code=prop,confirmed_code=conf,subject=source,duty_rate=duty)
                queue.set_auto_approve(prop,nv)
                st.toast(f"{'✅ Enabled' if nv else '⭕ Disabled'}: {prop} → {conf}")
                st.cache_data.clear()
                st.rerun()

    tab_on, tab_off = st.tabs([f"🟢 Auto-approve ON ({len(approved)})", f"⭕ Auto-approve OFF ({len(pending)})"])
    with tab_on:
        render_table(approved, "on")
    with tab_off:
        render_table(pending, "off")

    st.caption("Changes are saved immediately to Google Sheets.")
