# app.py
# Streamlit: Credit Request Status Summarizer (Rule-based + optional DeepSeek hybrid)

import io
import re
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse

import pandas as pd
import streamlit as st

# =========================
# Sidebar: data + options
# =========================
st.set_page_config(page_title="Credit Status Summarizer", layout="wide")

st.sidebar.title("⚙️ Options")
use_hybrid = st.sidebar.toggle("Use hybrid (DeepSeek for edge cases)", value=False,
                               help="Fast rules by default. Calls your chat() only when status is long/ambiguous.")
n_sample = st.sidebar.slider("Sample size (preview)", 5, 50, 20, help="Rows shown in the preview table.")
randomize = st.sidebar.button("🔀 Shuffle sample")

st.sidebar.markdown("---")
st.sidebar.caption("Upload your CSV exported from iTop / Firebase:")
uploaded = st.sidebar.file_uploader("CSV file", type=["csv"])

st.sidebar.markdown("---")
st.sidebar.caption("Tip: If running inside Colab, you can `df.to_csv()` then upload here.")

# Optional: a simple 'chat' function hook for DeepSeek
# Replace this stub with your real DeepSeek chat() if you enable hybrid mode.
def chat(messages, max_new_tokens=24, temperature=0.0):
    # Stub: if you want hybrid, import your real chat() from your local setup.
    # from your_module import chat as deepseek_chat
    # return deepseek_chat(messages, max_new_tokens=max_new_tokens, temperature=temperature)
    raise RuntimeError("Hybrid mode enabled, but no DeepSeek chat() is wired. Provide your chat() implementation.")

# =========================
# Helpers (dates, rules)
# =========================
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
    cands = [_norm_dt(m.group(0)) for m in ISO_RX.finditer(text)] + \
            [_norm_dt(m.group(0)) for m in MONTH_RX.finditer(text)]
    cands = [c for c in cands if c]
    latest = max(cands) if cands else None

    target = None
    for kw in ("around", "on", "by", "expected", "due"):
        p = text.lower().find(kw)
        if p != -1:
            m = ISO_RX.search(text[p:]) or MONTH_RX.search(text[p:])
            if m:
                target = _norm_dt(m.group(0))
                break
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
    if has_cr:
        lead = "Resolved"
    elif "denied" in txt or "rejected" in txt:
        lead = "Denied"
    elif "posted" in txt:
        lead = "Posted"
    elif "submitted" in txt or "billing" in txt or "macro" in txt:
        lead = "Submitted"
    else:
        lead = "Pending"

    if has_cr:
        msg = f"{lead} — CR on file; ticket should be closed (CR#={cr_val})."
    else:
        msg = f"{lead}"
        if is_late:
            msg += " — Late."
        elif target:
            msg += f"; target={target}."
        elif latest:
            msg += f"; last_update={latest}."
        else:
            msg += "."

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

    # Constrained LLM rewrite
    sys = ("You are a Credit report analyst. Rewrite as ONE short, factual sentence (<=18 words). "
           "Allowed verbs: Pending, Submitted, Posted, Denied, Resolved. No preface, no reasoning.")
    usr = (f"Ticket: {row.get('Ticket Number','')}\n"
           f"Invoice: {row.get('Invoice Number','')}\n"
           f"Raw status: {meta['s_text']}\n"
           "Return only the single sentence.")
    try:
        out = chat([{"role": "system", "content": sys},
                    {"role": "user", "content": usr}],
                    max_new_tokens=24, temperature=0.0)
        final = [ln.strip() for ln in str(out).split("\n") if ln.strip()][-1]
        if not final.endswith((".", "!", "?")):
            final += "."
        return final, True
    except Exception:
        return rule_msg, False

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
        return "background-color: rgba(255,165,0,0.15)"  # On-track
    return df_in.style.applymap(_color, subset=["Status_Flag"])

# =========================
# Load data
# =========================
if uploaded is not None:
    df = pd.read_csv(uploaded, encoding="utf-8", low_memory=False)
    st.success(f"Loaded {len(df):,} rows, {len(df.columns)} columns.")
else:
    st.info("Upload a CSV to begin.")
    st.stop()

required_cols = {"Status", "Ticket Number", "Invoice Number", "RTN_CR_No"}
missing = required_cols - set(df.columns)
if missing:
    st.error(f"Missing required columns: {sorted(missing)}")
    st.stop()

# =========================
# Summarize
# =========================
st.header("🔎 Status Summaries")

# Full run (vectorized apply)
work = df.copy()
work[["AI_Status_Summary","_used_llm"]] = work.apply(
    lambda r: pd.Series(summarize_status_hybrid(r, use_llm=use_hybrid)),
    axis=1
)
work["Status_Flag"] = work["AI_Status_Summary"].apply(status_flag)

# Preview sample (random each click)
if randomize:
    sample = work.sample(n=min(n_sample, len(work)), replace=False)
else:
    sample = work.sample(n=min(n_sample, len(work)), replace=False, random_state=7)

preview_cols = [c for c in ["Ticket Number","Invoice Number","Item Number","Status","AI_Status_Summary","Status_Flag","_used_llm"] if c in work.columns]
st.subheader("Preview")
st.dataframe(style_flags(sample[preview_cols]), use_container_width=True, height=520)

# KPI row
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total", f"{len(work):,}")
col2.metric("Closed (CR on file)", f"{(work['Status_Flag']=='Closed').sum():,}")
col3.metric("Late", f"{(work['Status_Flag']=='Late').sum():,}")
col4.metric("Used LLM (hybrid)", f"{int(work['_used_llm'].sum()):,}")

# Filters and full table
st.subheader("Full Table")
flag_filter = st.multiselect("Filter by Status_Flag", options=["Closed","On-track","Late"], default=["Closed","On-track","Late"])
show = work.loc[work["Status_Flag"].isin(flag_filter), preview_cols]
st.dataframe(style_flags(show), use_container_width=True, height=680)

# Download
csv_bytes = work.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ Download enriched CSV", data=csv_bytes, file_name="credit_status_summaries.csv", mime="text/csv")

st.caption("Made with ⚡ rules + optional DeepSeek polish. Fast, deterministic, dashboard-ready.")
