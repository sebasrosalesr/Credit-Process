# streamlit_followups.py
import re
import pandas as pd
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse
import streamlit as st

# =========================
# Streamlit setup
# =========================
st.set_page_config(page_title="Monthly Follow-up Checker", page_icon="🧾", layout="wide")
st.title("🧾 Monthly Follow-up Dashboard")
st.caption("Identifies pending credit tickets with no CR or long inactivity (≥20 days).")

# =========================
# Firebase init
# =========================
@st.cache_resource(show_spinner=False)
def init_firebase():
    firebase_config = dict(st.secrets["firebase"])
    if "private_key" in firebase_config and "\\n" in firebase_config["private_key"]:
        firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(firebase_config)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
        })
    return True

init_firebase()

required_cols = {
    "Date","Status","Record ID","Ticket Number","Requested By",
    "Sales Rep","Issue Type","RTN_CR_No"
}
missing = [c for c in required_cols if c not in st.session_state.get("df", pd.DataFrame()).columns] \
          if "df" in st.session_state else list(required_cols)  # if df not in session, all are "missing"

if "df" in st.session_state and not missing:
    df = st.session_state["df"].copy()
else:
    st.info("⚠️ Please load your DataFrame `df` into `st.session_state['df']` before running.\n"
            "It must include: " + ", ".join(sorted(required_cols)))
    st.stop()

# ===== Monthly follow-up checker (runs on your `df`) =====
FOLLOWUP_UPDATE_DAYS = 20   # trigger if no update in >= N days
DATE_COL   = "Date"
STATUS_COL = "Status"

# --- Helpers ---
def parse_any_dt(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return pd.NaT
    try:
        return pd.to_datetime(dtparse(str(s), fuzzy=True))
    except Exception:
        return pd.NaT

BRACKET_DT = re.compile(r"\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\]")

def extract_status_last(status_str: str):
    """Find the last [YYYY-MM-DD HH:MM:SS] in a status blob and the trailing message."""
    if not isinstance(status_str, str) or not status_str.strip():
        return pd.NaT, "", 0
    matches = list(BRACKET_DT.finditer(status_str))
    if matches:
        last = matches[-1]
        last_dt = parse_any_dt(last.group(1))
        last_msg = status_str[last.end():].strip()
        last_msg = re.sub(r"^\s*(Update:|In\s*Process:|WIP:?)+\s*", "", last_msg, flags=re.I)
        return last_dt, last_msg, len(matches)
    # Fallback: try to parse the whole string as a date
    any_dt = parse_any_dt(status_str)
    return any_dt, (status_str or "").strip(), 0

def classify_state(full_status: str, last_msg: str):
    text = f"{full_status or ''} {last_msg or ''}".lower()
    if any(k in text for k in ["denied", "no credit warranted", "rejected"]): return "Denied"
    if any(k in text for k in ["approved", "submitted", "credit issued", "posted"]): return "Approved/Submitted"
    if any(k in text for k in ["resolved", "closing", "closed"]): return "Resolved/Closing"
    if any(k in text for k in ["wip", "in process", "pending", "delay", "delayed"]): return "In Process"
    return "Unknown"

def summarize_row(row):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    status = str(row.get(STATUS_COL, "") or "")
    req_dt = parse_any_dt(row.get(DATE_COL))
    last_dt, last_msg, _ = extract_status_last(status)
    if pd.isna(last_dt):  # if no timestamped updates, fall back to request date
        last_dt = req_dt

    days_open = int((now - req_dt).days) if pd.notna(req_dt) else None
    dsu       = int((now - last_dt).days) if pd.notna(last_dt) else None  # days since update
    state     = classify_state(status, last_msg)

    rtn = row.get("RTN_CR_No", None)
    has_cr = bool(str(rtn).strip()) if rtn is not None else False

    return {
        "Record ID": row.get("Record ID"),
        "Ticket Number": row.get("Ticket Number"),
        "Requested By": row.get("Requested By"),
        "Sales Rep": row.get("Sales Rep"),
        "Issue Type": row.get("Issue Type"),
        "request_dt": req_dt,
        "status_last_update_dt": last_dt,
        "status_last_msg": last_msg,
        "status_state": state,
        "days_open": days_open,
        "days_since_update": dsu,
        "RTN_CR_No": rtn,
        "has_cr_number": has_cr,
    }

def make_followup_or_status_message(s):
    """
    Generate either a follow-up message (if pending) or a resolution/no-action message (if closed/CR present).
    """
    def fmt_dt(x):
        return x.strftime("%Y-%m-%d %H:%M") if pd.notna(x) else "—"

    # ✅ Exception: status is Unknown but there IS a CR number → no follow-up required
    if s["status_state"] == "Unknown" and s["has_cr_number"]:
        subject = f"[No action] Ticket {s['Ticket Number']} has CR on file"
        body = (
            f"Ticket {s['Ticket Number']} (Record {s['Record ID']}) shows state *Unknown* but has a CR number "
            f"({s['RTN_CR_No']}).\n\n"
            f"- Issue Type: {s['Issue Type']}\n"
            f"- Opened: {fmt_dt(s['request_dt'])}\n"
            f"- Last update: {fmt_dt(s['status_last_update_dt'])} "
            f"(days since: {s['days_since_update']})\n\n"
            "No follow-up required. (Consider normalizing upstream status text.)"
        )
        return subject, body

    # ✅ Closed or CR present — short resolution message
    if s["has_cr_number"] or s["status_state"] in ["Approved/Submitted", "Resolved/Closing", "Denied"]:
        subject = f"[Resolved] Ticket {s['Ticket Number']} is already closed or processed"
        body = (
            f"Ticket {s['Ticket Number']} (Record {s['Record ID']}) is marked as *{s['status_state']}* "
            f"and has a CR number ({s['RTN_CR_No'] or 'N/A'}).\n\n"
            f"- Issue Type: {s['Issue Type']}\n"
            f"- Last update: {fmt_dt(s['status_last_update_dt'])}\n"
            f"- Closed days ago: {s['days_since_update']}\n\n"
            "No further follow-up needed unless an exception arises."
        )
        return subject, body

    # 🚨 Still pending or no CR — normal follow-up message
    reasons = []
    if not s["has_cr_number"]:
        reasons.append("missing CR number")
    if s["days_since_update"] is not None and s["days_since_update"] >= FOLLOWUP_UPDATE_DAYS:
        reasons.append(f"{s['days_since_update']} days without update")
    reason_txt = " and ".join(reasons) if reasons else "follow-up"

    subject = f"[Follow-up] Ticket {s['Ticket Number']} – {reason_txt}"
    body = (
        f"Hi Magician Darren,\n\n"
        f"Following up on ticket {s['Ticket Number']}).\n"
        f"- Issue Type: {s['Issue Type']}\n"
        f"- Opened: {fmt_dt(s['request_dt'])} (days open: {s['days_open']})\n"
        f"- Last update: {fmt_dt(s['status_last_update_dt'])} (days since: {s['days_since_update']})\n"
        f"- CR Number: {s['RTN_CR_No'] or 'None'}\n"
        f"- State: {s['status_state']}\n\n"
        "Request: please provide a status update and CR number (if issued), "
        "or an ETA for resolution.\n\nThanks!"
    )
    return subject, body

# ---- Pick a monthly range (edit these two lines) ----
# Keeping your exact hard-coded window; you can change here if needed.
range_start = "2025-08-01"
range_end   = "2025-09-30"

# Ensure Date is datetime (you already parsed, but this is safe)
df_range = df.copy()
df_range[DATE_COL] = pd.to_datetime(df_range[DATE_COL], errors="coerce")

mask = (df_range[DATE_COL] >= range_start) & (df_range[DATE_COL] <= range_end)
df_month = df_range.loc[mask].copy()

st.success(f"✅ Loaded {len(df_month)} tickets in range {range_start} → {range_end}")

# Summarize and flag (exactly as in your code)
summary = df_month.apply(summarize_row, axis=1, result_type="expand")

# 🧩 Add message generation (follow-up OR resolved) — same logic
summary[["message_subject", "message_body"]] = summary.apply(
    lambda s: pd.Series(make_followup_or_status_message(s)),
    axis=1
)

# 🔎 Optional: flag which ones still need follow-up — same condition
summary["needs_followup"] = (
    ((~summary["has_cr_number"]) | (summary["days_since_update"].fillna(-1) >= FOLLOWUP_UPDATE_DAYS))
    & ~((summary["status_state"] == "Unknown") & summary["has_cr_number"])
)

# Quick view (console-like info line replicated in app)
st.caption(f"🔴 Follow-ups to send: {int(summary['needs_followup'].sum())} / {len(summary)}")

# === Display exactly the same type of table you expect ===
# Show the full summary head like in your notebook preview
with st.expander("Preview (first 20 rows of full summary)", expanded=True):
    st.dataframe(summary.head(20), use_container_width=True)

# Also show the two message columns (full set) for convenience
st.subheader("📬 Messages")
st.dataframe(
    summary[["message_subject", "message_body"]],
    use_container_width=True
)

# Export — same columns as your code (entire summary)
out_path = "followups_{}_to_{}.csv".format(
    pd.to_datetime(range_start).strftime("%Y%m%d"),
    pd.to_datetime(range_end).strftime("%Y%m%d"),
)
csv_bytes = summary.to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    "⬇️ Download full summary CSV",
    data=csv_bytes,
    file_name=out_path,
    mime="text/csv"
)
