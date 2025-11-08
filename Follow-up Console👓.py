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
    dsu       = (now - last_dt).days if pd.notna(last_dt) else None
    state     = classify_state(status, last_msg)

    rtn = row.get("RTN_CR_No", None)
    has_cr = bool(str(rtn).strip()) if rtn is not None else False

    return {
        "Record ID": row.get("Record ID"),
        "Ticket Number": row.get("Ticket Number"),
        "Requested By": row.get("Requested By"),
        "Sales Rep": row.get("Sales Rep"),
        "Issue Type": row.get("Issue Type"),
        "status_state": state,
        "status_last_update_dt": last_dt,   # << added for messaging
        "status_last_msg": last_msg,
        "days_since_update": dsu,
        "request_dt": req_dt,
        "RTN_CR_No": rtn,
        "has_cr_number": has_cr,
    }

def make_followup_or_status_message(s):
    fmt = lambda x: x.strftime("%Y-%m-%d %H:%M") if pd.notna(x) else "—"
    dsu_txt = "—" if s["days_since_update"] is None else str(s["days_since_update"])

    # Unknown but CR present → no action
    if s["status_state"] == "Unknown" and s["has_cr_number"]:
        subj = f"[No action] Ticket {s['Ticket Number']} has CR on file"
        body = (
            f"Ticket {s['Ticket Number']} shows state *Unknown* but has CR ({s['RTN_CR_No']}).\n"
            f"- Issue: {s['Issue Type']}\n"
            f"- Opened: {fmt(s['request_dt'])}\n"
            f"- Last update: {fmt(s['status_last_update_dt'])} (days since: {dsu_txt})\n"
            "No follow-up required. (Consider normalizing upstream status text.)"
        )
        return subj, body

    # Closed or CR present → resolved
    if s["has_cr_number"] or s["status_state"] in ["Approved/Submitted","Resolved/Closing","Denied"]:
        subj = f"[Resolved] Ticket {s['Ticket Number']} is closed or processed"
        body = (
            f"Ticket {s['Ticket Number']} is *{s['status_state']}* with CR {s['RTN_CR_No'] or 'N/A'}.\n"
            f"- Last update: {fmt(s['status_last_update_dt'])} (days since: {dsu_txt})\n"
            "No further action required."
        )
        return subj, body

    # Still pending → follow-up
    reasons = []
    if not s["has_cr_number"]:
        reasons.append("missing CR number")
    if s["days_since_update"] is not None and s["days_since_update"] >= FOLLOWUP_UPDATE_DAYS:
        reasons.append(f"{s['days_since_update']} days without update")
    reason_txt = " and ".join(reasons) if reasons else "follow-up"

    subj = f"[Follow-up] Ticket {s['Ticket Number']} – {reason_txt}"
    body = (
        f"Following up on ticket {s['Ticket Number']}.\n"
        f"- Issue: {s['Issue Type']}\n"
        f"- Opened: {fmt(s['request_dt'])}\n"
        f"- Last update: {fmt(s['status_last_update_dt'])} (days since: {dsu_txt})\n"
        f"- CR: {s['RTN_CR_No'] or 'None'}\n"
        f"- State: {s['status_state']}\n\n"
        "Please provide a status update and CR number (if issued), or an ETA for resolution."
    )
    return subj, body

# --- SAFE wrapper to avoid "Columns must be same length as key"
def _safe_msg(s):
    try:
        sub, body = make_followup_or_status_message(s)
        return str(sub), str(body)
    except Exception as e:
        return "[Message error]", f"Failed to build message for {s.get('Ticket Number','?')}: {e}"

# =========================
# Date filter (last 3 months)
# =========================
today = pd.Timestamp.today().normalize()
range_start = today - pd.DateOffset(months=3)
df_month = df[(df["Date"] >= range_start) & (df["Date"] <= today)].copy()

# =========================
# Apply logic (robust)
# =========================
summary = df_month.apply(summarize_row, axis=1, result_type="expand")

if summary.empty:
    st.info("No tickets in the last 3 months for this view.")
    st.stop()

# Build messages safely and assign as two Series (avoids shape/key errors)
pairs = [ _safe_msg(row) for _, row in summary.iterrows() ]
summary["message_subject"] = [p[0] for p in pairs]
summary["message_body"]   = [p[1] for p in pairs]

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
c1, c2 = st.columns(2)
with c1:
    st.metric("🔴 Follow-ups", int(summary["needs_followup"].sum()))
with c2:
    st.metric("🟢 No action", int((~summary["needs_followup"]).sum()))

cols = ["Ticket Number","status_state","RTN_CR_No",
        "days_since_update","Follow-up Status","message_subject"]

df_view = summary.sort_values(
    by=["needs_followup","days_since_update"],
    ascending=[False, False],
    na_position="last"
)[cols]

st.dataframe(df_view, use_container_width=True)

with st.expander("📬 Full Message Details"):
    st.dataframe(
        summary[["Ticket Number","Follow-up Status","message_subject","message_body"]],
        use_container_width=True
    )
