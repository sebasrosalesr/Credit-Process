import os, json, re, requests
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from dateutil.parser import parse as dtparse
from dateutil.relativedelta import relativedelta
from datetime import datetime, timezone

st.set_page_config(page_title="Credit Status Summarizer", layout="wide")

log = st.sidebar.empty()  # live status box

# ---------- sanity: secrets present ----------
if "firebase" not in st.secrets:
    st.error("❌ Missing [firebase] in secrets. Add your service account in App → Settings → Secrets.")
    st.stop()

# ---------- Firebase init with visible errors ----------
@st.cache_resource(show_spinner=True)
def init_firebase():
    try:
        cfg = dict(st.secrets["firebase"])
        if "private_key" in cfg and "\\n" in cfg["private_key"]:
            cfg["private_key"] = cfg["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(cfg)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
            })
        return True
    except Exception as e:
        # show the error on the page to debug quickly
        st.exception(e)
        raise

ok = init_firebase()
log.info("✅ Firebase initialized")

# ---------- Safe fetch with timeout (REST fallback) ----------
COLUMNS = [
    "Corrected Unit Price","Credit Request Total","Credit Type","Customer Number","Date",
    "Extended Price","Invoice Number","Issue Type","Item Number","QTY","Reason for Credit",
    "Record ID","Requested By","Sales Rep","Status","Ticket Number","Unit Price","Type","RTN_CR_No"
]

def _safe_parse_dt(x):
    try: return dtparse(str(x), fuzzy=True)
    except: return pd.NaT

@st.cache_data(show_spinner=True, ttl=300)
def load_credit_requests_last_2_months():
    """
    Try Admin SDK first; if anything stalls, use REST with a short timeout to avoid hanging.
    """
    try:
        # Admin SDK – fast in most environments
        ref = db.reference("credit_requests")
        raw = ref.get()
    except Exception as e:
        # fallback to REST (public admin SDK usually bypasses rules; for REST you may need auth if rules block)
        st.warning(f"Admin SDK fetch failed ({e}). Trying REST fallback…")
        url = "https://creditapp-tm-default-rtdb.firebaseio.com/credit_requests.json"
        resp = requests.get(url, timeout=10)  # ⏱ 10s timeout
        resp.raise_for_status()
        raw = resp.json()

    raw = raw or {}
    rows = [{col: item.get(col, None) for col in COLUMNS} for item in raw.values()]
    df = pd.DataFrame(rows)

    df["Date"] = df["Date"].apply(_safe_parse_dt)
    df = df.dropna(subset=["Date"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - relativedelta(months=2)
    df = df[df["Date"] >= cutoff].copy().sort_values("Date", ascending=False)
    return df

try:
    df = load_credit_requests_last_2_months()
except Exception as e:
    st.exception(e)
    st.stop()

st.success(f"Loaded {len(df):,} credit requests from the last 2 months.")
st.dataframe(df[["Date","Ticket Number","Invoice Number","Status","RTN_CR_No"]].head(25), use_container_width=True)

# ---------- (Optional) DeepSeek chat hook ----------
def chat(messages, max_new_tokens=24, temperature=0.0):
    if use_hybrid:
        raise RuntimeError("Hybrid enabled, but no DeepSeek chat() wired. Set use_hybrid=False or provide chat().")
    return ""

# ---------- Helpers (dates, rules) ----------
ISO_RX   = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
MONTH_RX = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\,?\s+\d{2,4}\b", re.I)
CR_RX    = re.compile(r"\bCR[#:\-\s]*([A-Z0-9\-]{5,})\b", re.I)

def _norm_dt(s: str):
    try:
        return dtparse(s, fuzzy=True).date().isoformat()
    except Exception:
        return None

def extract_dates_any(text: str):
    if not isinstance(text, str):
        text = str(text or "")
    cands = [_norm_dt(m.group(0)) for m in ISO_RX.finditer(text)] + [_norm_dt(m.group(0)) for m in MONTH_RX.finditer(text)]
    cands = [c for c in cands if c]
    latest = max(cands) if cands else None
    target = None
    for kw in ("around","on","by","expected","due"):
        p = text.lower().find(kw)
        if p != -1:
            m = ISO_RX.search(text[p:]) or MONTH_RX.search(text[p:])
            if m:
                target = _norm_dt(m.group(0)); break
    return latest, target

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
        except Exception:
            pass

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
    meta = dict(has_cr=has_cr, latest=latest, target=target, s_text=s_text)
    return msg.strip(), meta

def needs_llm(meta: dict) -> bool:
    s = meta["s_text"]
    longish = len(s) > 120
    multi   = s.count(".") + s.count(";") + s.count("]") >= 2
    low_sig = (not meta["has_cr"]) and (meta["target"] is None) and (meta["latest"] is None)
    return low_sig and (longish or multi)

def summarize_status_hybrid(row, use_llm=False):
    rule_msg, meta = summarize_status_rule(row)
    if not (use_llm and needs_llm(meta)):
        return rule_msg, False
    # Constrained LLM rewrite (requires real chat())
    sys = ("You are a Credit report analyst. Rewrite as ONE short, factual sentence (<=18 words). "
           "Allowed verbs: Pending, Submitted, Posted, Denied, Resolved. No preface, no reasoning.")
    usr = (f"Ticket: {row.get('Ticket Number','')}\n"
           f"Invoice: {row.get('Invoice Number','')}\n"
           f"Raw status: {meta['s_text']}\n"
           "Return only the single sentence.")
    out = chat([{"role":"system","content":sys},{"role":"user","content":usr}],
               max_new_tokens=24, temperature=0.0)
    final = [ln.strip() for ln in str(out).split("\n") if ln.strip()][-1]
    if not final.endswith((".", "!", "?")): final += "."
    return final, True

def status_flag(summary: str) -> str:
    if "CR on file" in summary or summary.startswith("Resolved"):
        return "Closed"
    if "Late" in summary:
        return "Late"
    return "On-track"

def style_flags(df_in: pd.DataFrame) -> pd.io.formats.style.Styler:
    def _color(v):
        if v == "Closed": return "background-color: rgba(0,200,0,0.15)"
        if v == "Late":   return "background-color: rgba(255,0,0,0.15)"
        return "background-color: rgba(255,165,0,0.15)"
    return df_in.style.applymap(_color, subset=["Status_Flag"])

# ---------- Summarize once ----------
work = df.copy()
work[["AI_Status_Summary","_used_llm"]] = work.apply(
    lambda r: pd.Series(summarize_status_hybrid(r, use_llm=use_hybrid)),
    axis=1
)
work["Status_Flag"] = work["AI_Status_Summary"].apply(status_flag)

# ---------- Preview ----------
st.header("🔎 Status Summaries")
sample = work.sample(n=min(n_sample, len(work)), replace=False if randomize else False, random_state=None if randomize else 7)
preview_cols = [c for c in ["Date","Ticket Number","Invoice Number","Item Number","Status","AI_Status_Summary","Status_Flag","_used_llm"] if c in work.columns]
st.subheader("Preview")
st.dataframe(style_flags(sample[preview_cols]), use_container_width=True, height=520)

# ---------- KPIs ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", f"{len(work):,}")
c2.metric("Closed (CR on file)", f"{(work['Status_Flag']=='Closed').sum():,}")
c3.metric("Late", f"{(work['Status_Flag']=='Late').sum():,}")
c4.metric("Used LLM (hybrid)", f"{int(work['_used_llm'].sum()):,}")

# ---------- Full table + download ----------
st.subheader("Full Table")
flag_filter = st.multiselect("Filter by Status_Flag", options=["Closed","On-track","Late"], default=["Closed","On-track","Late"])
show = work.loc[work["Status_Flag"].isin(flag_filter), preview_cols]
st.dataframe(style_flags(show), use_container_width=True, height=680)

csv_bytes = work.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ Download enriched CSV", data=csv_bytes, file_name="credit_status_summaries.csv", mime="text/csv")
