# app.py — Firebase + Hybrid Status Summarizer (minimal columns)

import time, traceback, re, requests
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from dateutil.parser import parse as dtparse
from dateutil.relativedelta import relativedelta
from datetime import datetime, timezone

# =========================
# Page & Sidebar
# =========================
st.set_page_config(page_title="Credit Status Summarizer", layout="wide")
st.write("🚦 App boot…")

N_SAMPLE = st.sidebar.slider("Sample size (preview)", 5, 50, 15)
RANDOMIZE = st.sidebar.button("🔀 Shuffle sample")
USE_LLM = st.sidebar.toggle("Use hybrid LLM polish", value=False)

def _t(): return time.perf_counter()
def _safe_parse_dt(x):
    try: return dtparse(str(x), fuzzy=True)
    except: return pd.NaT

# =========================
# Firebase init from secrets
# =========================
if "firebase" not in st.secrets:
    st.error("❌ Missing [firebase] in secrets.")
    st.stop()

t0 = _t()
try:
    cfg = dict(st.secrets["firebase"])
    if "private_key" in cfg and "\\n" in cfg["private_key"]:
        cfg["private_key"] = cfg["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(cfg)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
        })
    st.write(f"✅ Firebase init in {(_t()-t0)*1000:.0f} ms")
except Exception:
    st.error("Firebase init failed:")
    st.code(traceback.format_exc())
    st.stop()

# =========================
# Fetch last 2 months (Admin SDK with REST fallback + timeout)
# =========================
COLUMNS = [
    "Corrected Unit Price","Credit Request Total","Credit Type","Customer Number","Date",
    "Extended Price","Invoice Number","Issue Type","Item Number","QTY","Reason for Credit",
    "Record ID","Requested By","Sales Rep","Status","Ticket Number","Unit Price","Type","RTN_CR_No"
]

@st.cache_data(show_spinner=True, ttl=300)
def fetch_last_2_months():
    t1 = _t()
    try:
        ref = db.reference("credit_requests")
        raw = ref.get()
        src = "AdminSDK"
    except Exception:
        url = "https://creditapp-tm-default-rtdb.firebaseio.com/credit_requests.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        src = "REST"
    dur_fetch = (_t()-t1)*1000

    raw = raw or {}
    rows = [{col: item.get(col, None) for col in COLUMNS} for item in raw.values()]
    df = pd.DataFrame(rows)

    t2 = _t()
    df["Date"] = df["Date"].apply(_safe_parse_dt)
    df = df.dropna(subset=["Date"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - relativedelta(months=2)
    df = df[df["Date"] >= cutoff].copy().sort_values("Date", ascending=False)
    dur_parse = (_t()-t2)*1000
    return df, src, dur_fetch, dur_parse

try:
    df, src, dur_fetch, dur_parse = fetch_last_2_months()
    st.write(f"📥 Fetch via **{src}**: {dur_fetch:.0f} ms | 🧮 Parse+filter: {dur_parse:.0f} ms | Rows: {len(df):,}")
    st.dataframe(df.head(8), use_container_width=True)
except Exception:
    st.error("Load failed:")
    st.code(traceback.format_exc())
    st.stop()

# =========================
# HYBRID STATUS SUMMARIZER (your logic, wired here)
# =========================

# --- lightweight chat stub (wire your DeepSeek call here if desired) ---
def chat(messages, max_new_tokens=24, temperature=0.0):
    if not USE_LLM:
        return ""   # fallback to rules
    # If you wire an LLM, return a single short sentence string here.
    # For safety, we'll return empty if not wired:
    return ""

# --- Extractors (as provided) ---
def extract_dates_any(text):
    ISO_RX   = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
    MONTH_RX = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\,?\s+\d{2,4}\b", re.I)
    def _norm(s):
        try: return dtparse(s, fuzzy=True).date().isoformat()
        except: return None
    if not isinstance(text, str): text = str(text or "")
    cands = [_norm(m.group(0)) for m in ISO_RX.finditer(text)] + [_norm(m.group(0)) for m in MONTH_RX.finditer(text)]
    cands = [c for c in cands if c]
    latest = max(cands) if cands else None

    target = None
    for kw in ("around","on","by","expected","due"):
        p = text.lower().find(kw)
        if p != -1:
            m = ISO_RX.search(text[p:]) or MONTH_RX.search(text[p:])
            if m:
                target = _norm(m.group(0)); break
    return latest, target

CR_RX = re.compile(r"\bCR[#:\-\s]*([A-Z0-9\-]{5,})\b", re.I)

def summarize_status_rule(row):
    s_text = str(row.get("Status") or "").strip()
    latest, target = extract_dates_any(s_text)

    cr_val = str(row.get("RTN_CR_No") or "").strip()
    m = CR_RX.search(s_text)
    if m and not cr_val:
        cr_val = m.group(1)
    has_cr = bool(cr_val)

    is_late = False
    if target and not has_cr:
        try:
            is_late = datetime.fromisoformat(target).date() < datetime.now(timezone.utc).date()
        except: pass

    txt = s_text.lower()
    if has_cr: lead = "Resolved"
    elif "denied" in txt or "rejected" in txt: lead = "Denied"
    elif "posted" in txt: lead = "Posted"
    elif "submitted" in txt or "billing" in txt or "macro" in txt: lead = "Submitted"
    else: lead = "Pending"

    if has_cr:
        msg = f"{lead} — CR on file; ticket should be closed (CR#={cr_val})."
    else:
        msg = f"{lead}"
        if is_late: msg += " — Late."
        elif target: msg += f"; target={target}."
        elif latest: msg += f"; last_update={latest}."
        else: msg += "."
    return msg.strip(), dict(has_cr=has_cr, latest=latest, target=target, lead=lead, s_text=s_text)

def needs_llm(meta: dict) -> bool:
    s = meta["s_text"]
    longish = len(s) > 120
    multi   = s.count(".") + s.count(";") + s.count("]") >= 2
    low_sig = (not meta["has_cr"]) and (meta["target"] is None) and (meta["latest"] is None)
    return USE_LLM and (low_sig and (longish or multi))

def summarize_status_hybrid(row):
    rule_msg, meta = summarize_status_rule(row)
    if not needs_llm(meta):
        return rule_msg  # fast path

    context = {
        "Ticket Number": row.get("Ticket Number", ""),
        "Invoice Number": row.get("Invoice Number", ""),
        "Status": meta["s_text"]
    }
    sys = (
        "You are a Credit report analyst. Rewrite the status as ONE short, factual sentence (<= 18 words). "
        "Prefer these verbs: Pending, Submitted, Posted, Denied, Resolved. "
        "Do NOT explain your reasoning. No prefaces. No quotes."
    )
    usr = (
        "Data:\n"
        f"- Ticket: {context['Ticket Number']}\n"
        f"- Invoice: {context['Invoice Number']}\n"
        f"- Raw status: {context['Status']}\n\n"
        "Return only the single sentence."
    )
    try:
        msg = chat(
            [{"role":"system","content":sys},{"role":"user","content":usr}],
            max_new_tokens=24,
            temperature=0.0
        )
        msg = [ln.strip() for ln in str(msg).split("\n") if ln.strip()]
        msg = msg[-1] if msg else ""
        if not msg:
            return rule_msg
        if not msg.endswith((".", "!", "?")): msg += "."
        return msg
    except Exception:
        return rule_msg

def status_flag(summary: str) -> str:
    if "CR on file" in summary or summary.startswith("Resolved"):
        return "Closed"
    if "Late" in summary:
        return "Late"
    return "On-track"

# =========================
# Build minimal view from Firebase df
# =========================
work = df.copy()
work["AI_Status_Summary"] = work.apply(summarize_status_hybrid, axis=1)
work["Status_Flag"] = work["AI_Status_Summary"].apply(status_flag)

DISPLAY_COLS = [
    "Ticket Number", "Invoice Number", "Item Number", "Status", "AI_Status_Summary"
]
have = [c for c in DISPLAY_COLS if c in work.columns]
view = work[have].copy()

# =========================
# Preview + Full + Download
# =========================
st.header("🔎 Status Summaries (sample)")
sample = view.sample(n=min(N_SAMPLE, len(view)),
                     random_state=None if RANDOMIZE else 7)
st.dataframe(sample, use_container_width=True, height=520)

st.subheader("Full Table")
st.dataframe(view, use_container_width=True, height=680)

csv_bytes = view.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ Download CSV",
                   data=csv_bytes,
                   file_name="credit_status_summaries_minimal.csv",
                   mime="text/csv")
