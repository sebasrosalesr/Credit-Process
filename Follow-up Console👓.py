# streamlit_followup_app.py
import re
import pandas as pd
import streamlit as st
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse
from firebase_admin import credentials, db
import firebase_admin

# -----------------------------
# Streamlit setup
# -----------------------------
st.set_page_config(page_title="Credit Request Follow-ups", page_icon="🧾", layout="wide")
st.title("🧾 Monthly Follow-up Dashboard")
st.caption("Identifies pending credit tickets with no CR or long inactivity (>20 days).")

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

# =========================
# Load data
# =========================
@st.cache_data(show_spinner=True, ttl=120)
def load_data():
    cols = [
        "Record ID","Ticket Number","Requested By","Sales Rep","Issue Type","Date",
        "Status","RTN_CR_No"
    ]
    ref = db.reference("credit_requests")
    raw = ref.get() or {}
    data = [{c: v.get(c, None) for c in cols} for v in raw.values()]
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    return df

df = load_data()

# =========================
# Logic helpers
# =========================
FOLLOWUP_UPDATE_DAYS = 20
DATE_COL, STATUS_COL = "Date", "Status"
BRACKET_DT = re.compile(r"\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\]")

def parse_any_dt(s):
    try:
        return pd.to_datetime(dtparse(str(s), fuzzy=True))
    except Exception:
        return pd.NaT

def extract_status_last(status_str):
    if not isinstance(status_str, str) or not status_str.strip():
        return pd.NaT, "", 0
    matches = list(BRACKET_DT.finditer(status_str))
    if matches:
        last = matches[-1]
        last_dt = parse_any_dt(last.group(1))
        last_msg = status_str[last.end():].strip()
        last_msg = re.sub(r"^\s*(Update:|In\s*Process:|WIP:?)+\s*", "", last_msg, flags=re.I)
        return last_dt, last_msg, len(matches)
    return parse_any_dt(status_str), status_str.strip(), 0

def classify_state(full_status, last_msg):
    text = f"{full_status or ''} {last_msg or ''}".lower()
    if any(k in text for k in ["denied","no credit warranted","rejected"]): return "Denied"
    if any(k in text for k in ["approved","submitted","credit issued","posted"]): return "Approved/Submitted"
    if any(k in text for k in ["resolved","closing","closed"]): return "Resolved/Closing"
    if any(k in text for k in ["wip","in process","pending","delay","delayed"]): return "In Process"
    return "Unknown"

def summarize_row(row):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = str(row.get(STATUS_COL, "") or "")
    req_dt = parse_any_dt(row.get(DATE_COL))
    last_dt, last_msg, _ = extract_status_last(status)
    if pd.isna(last_dt):
        last_dt = req_dt
    days_open = (now - req_dt).days if pd.notna(req_dt) else None
    dsu = (now - last_dt).days if pd.notna(last_dt) else None
    state = classify_state(status, last_msg)
    rtn = row.get("RTN_CR_No", None)
    has_cr = bool(str(rtn).strip()) if rtn is not None else False
    return {
        "Record ID": row.get("Record ID"),
        "Ticket Number": row.get("Ticket Number"),
        "Requested By": row.get("Requested By"),
        "Sales Rep": row.get("Sales Rep"),
        "Issue Type": row.get("Issue Type"),
        "status_state": state,
        "days_since_update": dsu,
        "RTN_CR_No": rtn,
        "has_cr_number": has_cr,
        "status_last_msg": last_msg,
        "request_dt": req_dt
    }

def make_followup_or_status_message(s):
    fmt = lambda x: x.strftime("%Y-%m-%d %H:%M") if pd.notna(x) else "—"
    if s["status_state"] == "Unknown" and s["has_cr_number"]:
        subj = f"[No action] Ticket {s['Ticket Number']} has CR on file"
        msg = (
            f"Ticket {s['Ticket Number']} shows state *Unknown* but has CR ({s['RTN_CR_No']}).\n"
            f"- Issue: {s['Issue Type']}\n- Opened: {fmt(s['request_dt'])}\n"
            f"- Last update: {fmt(s['request_dt'])} (days since {s['days_since_update']})\n"
            "No follow-up required. Normalize upstream status text."
        )
        return subj, msg
    if s["has_cr_number"] or s["status_state"] in ["Approved/Submitted","Resolved/Closing","Denied"]:
        subj = f"[Resolved] Ticket {s['Ticket Number']} is closed or processed"
        msg = (
            f"Ticket {s['Ticket Number']} is *{s['status_state']}* with CR {s['RTN_CR_No'] or 'N/A'}.\n"
            f"Last update {fmt(s['request_dt'])}. No further action required."
        )
        return subj, msg
    reasons = []
    if not s["has_cr_number"]:
        reasons.append("missing CR number")
    if s["days_since_update"] and s["days_since_update"] >= FOLLOWUP_UPDATE_DAYS:
        reasons.append(f"{s['days_since_update']} days w/out update")
    reason_txt = " and ".join(reasons) if reasons else "follow-up"
    subj = f"[Follow-up] Ticket {s['Ticket Number']} – {reason_txt}"
    msg = (
        f"Following up on ticket {s['Ticket Number']}.\n"
        f"- Issue: {s['Issue Type']}\n"
        f"- Last update: {fmt(s['request_dt'])} (days since {s['days_since_update']})\n"
        f"- CR: {s['RTN_CR_No'] or 'None'}\n- State: {s['status_state']}\n"
        "Please update status or provide ETA. Thanks!"
    )
    return subj, msg

# =========================
# Date filter (last 3 months)
# =========================
today = pd.Timestamp.today().normalize()
range_start = today - pd.DateOffset(months=3)
df_month = df[(df["Date"] >= range_start) & (df["Date"] <= today)].copy()

# =========================
# Apply logic
# =========================
summary = df_month.apply(summarize_row, axis=1, result_type="expand")
summary[["message_subject","message_body"]] = summary.apply(
    lambda s: pd.Series(make_followup_or_status_message(s)), axis=1
)
summary["needs_followup"] = (
    ((~summary["has_cr_number"]) | (summary["days_since_update"].fillna(-1) >= FOLLOWUP_UPDATE_DAYS))
    & ~((summary["status_state"] == "Unknown") & summary["has_cr_number"])
)
summary["Follow-up Status"] = summary["needs_followup"].map(
    {True: "🔴 Needs follow-up", False: "🟢 No follow-up required"}
)

# =========================
# Display summary
# =========================
st.metric("🔴 Follow-ups", int(summary["needs_followup"].sum()))
st.metric("🟢 No action", int((~summary["needs_followup"]).sum()))

cols = ["Ticket Number","Issue Type","status_state","RTN_CR_No","days_since_update","Follow-up Status","message_subject"]
st.dataframe(
    summary.sort_values(["needs_followup","days_since_update"], ascending=[False, False])[cols],
    use_container_width=True
)

with st.expander("📬 Full Message Details"):
    st.dataframe(summary[["Ticket Number","Follow-up Status","message_subject","message_body"]], use_container_width=True)
