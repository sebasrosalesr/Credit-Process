# app.py — Monthly follow-up console (last 3 months, auto)
import re
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse
from dateutil.relativedelta import relativedelta

import pandas as pd
import streamlit as st

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, db

# -----------------------------
# UI CONFIG
# -----------------------------
st.set_page_config(page_title="Credit Requests — Follow-ups", page_icon="🧾", layout="wide")
st.title("🧾 Credit Requests — Follow-ups (last 3 months)")
st.caption("Flags tickets missing CR or with stale updates. Unknown+CR → no action.")

# =========================
# Firebase init (your function)
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

# =========================
# Load -> DataFrame (cached)
# =========================
COLS = [
    "Corrected Unit Price","Credit Request Total","Credit Type","Customer Number","Date",
    "Extended Price","Invoice Number","Issue Type","Item Number","QTY","Reason for Credit",
    "Record ID","Requested By","Sales Rep","Status","Ticket Number","Unit Price","Type","RTN_CR_No"
]

@st.cache_data(show_spinner=True, ttl=120)
def load_df() -> pd.DataFrame:
    ref = db.reference("credit_requests")
    raw = ref.get() or {}
    rows = []
    for v in raw.values():
        rows.append({c: v.get(c, None) for c in COLS})
    df = pd.DataFrame(rows)

    # robust date parse
    def parse_any(s):
        try:
            return pd.to_datetime(dtparse(str(s), fuzzy=True))
        except Exception:
            return pd.NaT

    df["Date"] = df["Date"].apply(parse_any)
    df = df.dropna(subset=["Date"])
    return df

df = load_df()

# =========================
# Helper functions
# =========================
FOLLOWUP_UPDATE_DAYS = 20   # trigger if no update in ≥ N days
DATE_COL   = "Date"
STATUS_COL = "Status"

BRACKET_DT = re.compile(r"\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\]")

def extract_status_last(status_str: str):
    if not isinstance(status_str, str) or not status_str.strip():
        return pd.NaT, "", 0
    matches = list(BRACKET_DT.finditer(status_str))
    if matches:
        last = matches[-1]
        def parse_dt(s):
            try: return pd.to_datetime(dtparse(s))
            except: return pd.NaT
        last_dt = parse_dt(last.group(1))
        last_msg = status_str[last.end():].strip()
        last_msg = re.sub(r"^\s*(Update:|In\s*Process:|WIP:?)+\s*", "", last_msg, flags=re.I)
        return last_dt, last_msg, len(matches)
    # fallback: try whole string
    try:
        any_dt = pd.to_datetime(dtparse(status_str))
    except:
        any_dt = pd.NaT
    return any_dt, (status_str or "").strip(), 0

def classify_state(full_status: str, last_msg: str):
    text = f"{full_status or ''} {last_msg or ''}".lower()
    if any(k in text for k in ["denied", "no credit warranted", "rejected"]): return "Denied"
    if any(k in text for k in ["approved", "submitted", "credit issued", "posted"]): return "Approved/Submitted"
    if any(k in text for k in ["resolved", "closing", "closed"]): return "Resolved/Closing"
    if any(k in text for k in ["wip", "in process", "pending", "delay", "delayed"]): return "In Process"
    return "Unknown"

def summarize_row(row: pd.Series):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = str(row.get(STATUS_COL, "") or "")
    req_dt = row.get(DATE_COL)
    last_dt, last_msg, _ = extract_status_last(status)
    if pd.isna(last_dt): last_dt = req_dt

    days_open = int((now - req_dt).days) if pd.notna(req_dt) else None
    dsu       = int((now - last_dt).days) if pd.notna(last_dt) else None
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
    def fmt_dt(x): return x.strftime("%Y-%m-%d %H:%M") if pd.notna(x) else "—"

    # Exception: Unknown + CR → no action
    if s["status_state"] == "Unknown" and s["has_cr_number"]:
        subject = f"[No action] Ticket {s['Ticket Number']} has CR on file"
        body = (
            f"Ticket {s['Ticket Number']} (Record {s['Record ID']}) shows state *Unknown* but has a CR number "
            f"({s['RTN_CR_No']}).\n\n"
            f"- Issue Type: {s['Issue Type']}\n"
            f"- Opened: {fmt_dt(s['request_dt'])}\n"
            f"- Last update: {fmt_dt(s['status_last_update_dt'])} (days since: {s['days_since_update']})\n\n"
            "No follow-up required. (Consider normalizing upstream status text.)"
        )
        return subject, body

    # Closed-ish or CR present
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

    # Follow-up
    reasons = []
    if not s["has_cr_number"]:
        reasons.append("missing CR number")
    if s["days_since_update"] is not None and s["days_since_update"] >= FOLLOWUP_UPDATE_DAYS:
        reasons.append(f"{s['days_since_update']} days without update")
    reason_txt = " and ".join(reasons) if reasons else "follow-up"

    subject = f"[Follow-up] Ticket {s['Ticket Number']} – {reason_txt}"
    body = (
        f"Hi team,\n\n"
        f"Following up on ticket {s['Ticket Number']} (Record {s['Record ID']}).\n"
        f"- Issue Type: {s['Issue Type']}\n"
        f"- Opened: {fmt_dt(s['request_dt'])} (days open: {s['days_open']})\n"
        f"- Last update: {fmt_dt(s['status_last_update_dt'])} (days since: {s['days_since_update']})\n"
        f"- CR Number: {s['RTN_CR_No'] or 'None'}\n"
        f"- State: {s['status_state']}\n\n"
        "Request: please provide a status update and CR number (if issued), or an ETA for resolution.\n\nThanks!"
    )
    return subject, body

# =========================
# Date window: last 3 months (hard-coded relative to today)
# =========================
today = pd.Timestamp.today().normalize()
range_start = (today - relativedelta(months=3)).replace(day=1)  # start of month 3 months ago
range_end   = today  # today

st.caption(f"Date window: **{range_start.date()} → {range_end.date()}** (last 3 months)")

df_range = df.copy()
df_range[DATE_COL] = pd.to_datetime(df_range[DATE_COL], errors="coerce")
mask = (df_range[DATE_COL] >= range_start) & (df_range[DATE_COL] <= range_end)
df_month = df_range.loc[mask].copy()

st.write(f"✅ Loaded **{len(df_month)}** tickets in range.")

# =========================
# Summarize + flags + messages
# =========================
summary = df_month.apply(summarize_row, axis=1, result_type="expand")

# Normalize for robust comparisons
summary["status_state"] = summary["status_state"].astype(str).str.strip()

summary[["message_subject","message_body"]] = summary.apply(
    lambda s: pd.Series(make_followup_or_status_message(s)),
    axis=1
)

summary["needs_followup"] = (
    ((~summary["has_cr_number"]) | (summary["days_since_update"].fillna(-1) >= FOLLOWUP_UPDATE_DAYS))
    & ~((summary["status_state"].str.lower() == "unknown") & summary["has_cr_number"])
)

# Color flag
summary["Follow-up Status"] = summary["needs_followup"].map(
    {True: "🔴 Needs follow-up", False: "🟢 No follow-up required"}
)

# =========================
# Display
# =========================
left, right = st.columns([1,1])
with left:
    st.metric("🔴 Follow-ups", int(summary["needs_followup"].sum()))
with right:
    st.metric("🟢 No action", int((~summary["needs_followup"]).sum()))

cols_show = [
    "Ticket Number","Issue Type","status_state","RTN_CR_No","days_since_update",
    "Follow-up Status","message_subject"
]
st.dataframe(
    summary[cols_show].sort_values(["needs_followup","days_since_update"], ascending=[False, False]),
    use_container_width=True
)

# Details expander
with st.expander("Show full messages"):
    st.dataframe(
        summary[["Ticket Number","Follow-up Status","message_subject","message_body"]],
        use_container_width=True
    )

# =========================
# Export
# =========================
csv = summary.to_csv(index=False, encoding="utf-8-sig")
st.download_button("⬇️ Download CSV", data=csv, file_name=f"followups_{range_start:%Y%m%d}_to_{range_end:%Y%m%d}.csv", mime="text/csv")
