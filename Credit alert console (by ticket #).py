# app.py
import re
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse

import pandas as pd
import streamlit as st
import numpy as np

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, db

# -----------------------------
# UI CONFIG
# -----------------------------
st.set_page_config(page_title="Ticket Checker", page_icon="🎫", layout="centered")
st.title("🎫 Ticket Checker")
st.caption("Search a single ticket. See last update, staleness, CR number, and full history.")

# =========================
# Firebase init (simple + cached)
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
# Load one time (cached) -> DataFrame
# =========================
@st.cache_data(show_spinner=False, ttl=60)
def load_df() -> pd.DataFrame:
    ref = db.reference("credit_requests")
    raw = ref.get() or {}
    cols = [
        "Record ID","Ticket Number","Requested By","Sales Rep","Issue Type",
        "Date","Status","RTN_CR_No"
    ]
    rows = [{c: v.get(c) for c in cols} for v in raw.values()]
    return pd.DataFrame(rows)

df = load_df()

# =========================
# Helpers (from your notebook)
# =========================
def parse_any_dt(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return pd.NaT
    try: return pd.to_datetime(dtparse(str(s), fuzzy=True))
    except Exception: return pd.NaT

BRACKET_DT = re.compile(r"\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\]")

def extract_status_last(status_str: str):
    if not isinstance(status_str, str) or not status_str.strip():
        return pd.NaT, "", 0
    matches = list(BRACKET_DT.finditer(status_str))
    if matches:
        last = matches[-1]
        last_dt = parse_any_dt(last.group(1))
        last_msg = status_str[last.end():].strip()
        last_msg = re.sub(r"^\s*(Update:|In\s*Process:|WIP:?)+\s*", "", last_msg, flags=re.I)
        return last_dt, last_msg, len(matches)
    any_dt = parse_any_dt(status_str)
    return any_dt, status_str.strip(), 0

def extract_status_history(status_str: str):
    if not isinstance(status_str, str) or not status_str.strip():
        return []
    parts = []
    matches = list(BRACKET_DT.finditer(status_str))
    if not matches:
        return [{"ts": parse_any_dt(status_str), "text": status_str.strip()}]
    for i, m in enumerate(matches):
        ts = parse_any_dt(m.group(1))
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(status_str)
        text = status_str[start:end].strip()
        text = re.sub(r"^\s*(Update:|In\s*Process:|WIP:?)+\s*", "", text, flags=re.I)
        parts.append({"ts": ts, "text": text})
    parts = sorted(parts, key=lambda x: (pd.isna(x["ts"]), x["ts"]))
    return parts

def classify_state(full_status: str, last_msg: str):
    text = f"{full_status or ''} {last_msg or ''}".lower()
    if any(k in text for k in ["denied", "no credit warranted", "rejected"]): return "Denied"
    if any(k in text for k in ["approved", "submitted", "credit issued", "posted"]): return "Approved/Submitted"
    if any(k in text for k in ["resolved", "closing", "closed"]): return "Resolved/Closing"
    if any(k in text for k in ["wip", "in process", "pending", "delay", "delayed"]): return "In Process"
    return "Unknown"

STALE_UPDATE_DAYS = 21   # your chosen thresholds
STALE_OPEN_DAYS   = 30

def summarize_row(row: pd.Series):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = str(row.get("Status", "") or "")
    req_dt = parse_any_dt(row.get("Date"))
    last_dt, last_msg, n_updates = extract_status_last(status)
    if pd.isna(last_dt): last_dt = req_dt
    days_open = int((now - req_dt).days) if pd.notna(req_dt) else None
    dsu       = int((now - last_dt).days) if pd.notna(last_dt) else None
    state = classify_state(status, last_msg)
    rtn = row.get("RTN_CR_No", None)
    has_cr = False if rtn is None else (str(rtn).strip() != "")
    is_closedish = (state in ["Resolved/Closing", "Approved/Submitted", "Denied"]) or \
                   (re.search(r"\bclosed\b", status, flags=re.I) is not None)

    stale_reason = None
    if not is_closedish:
        if dsu is not None and dsu >= STALE_UPDATE_DAYS:
            stale_reason = f"No status update in ≥{STALE_UPDATE_DAYS} days"
        elif days_open is not None and days_open >= STALE_OPEN_DAYS:
            stale_reason = f"Open for ≥{STALE_OPEN_DAYS} days"
        elif not has_cr:
            stale_reason = "Missing CR Number"

    if is_closedish: alert = "GREEN"
    elif (dsu is not None and dsu >= STALE_UPDATE_DAYS) or (days_open is not None and days_open >= STALE_OPEN_DAYS):
        alert = "RED"
    elif not has_cr:
        alert = "YELLOW"
    else:
        alert = "GREEN"

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
        "stale_reason": stale_reason,
        "alert": alert,
        "history": extract_status_history(status)
    }

# =========================
# Search UI (single ticket)
# =========================
with st.form("search"):
    tnum = st.text_input("Ticket Number", value="")
    submitted = st.form_submit_button("Search", type="primary")

if submitted:
    # find ticket
    if tnum:
        sub = df[df["Ticket Number"].astype(str) == tnum]
    else:
        sub = pd.DataFrame()

    if sub.empty:
        st.error("❌ Ticket not found.")
    else:
        # if multiple, pick most recently updated
        if len(sub) > 1:
            tmp = sub.copy()
            tmp["_req_dt"]  = tmp["Date"].apply(parse_any_dt)
            tmp["_last_dt"] = tmp["Status"].apply(lambda s: extract_status_last(str(s))[0] or pd.NaT)
            sub = tmp.sort_values(["_last_dt","_req_dt"], ascending=[False, False]).head(1)

        summary = summarize_row(sub.iloc[0])

        # console-style output (monospace)
        badge = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(summary["alert"], "⚪️")
        st.markdown("```text\n" +
            "—"*68 + "\n" +
            f"🎫 Ticket: {summary['Ticket Number']}  |  Record: {summary['Record ID']}\n" +
            f"Requester: {summary['Requested By']}  |  Sales Rep: {summary['Sales Rep']}\n" +
            f"Issue: {summary['Issue Type']}\n" +
            f"State: {summary['status_state']}  |  Alert: {summary['alert']} {badge}\n" +
            f"Opened: {summary['request_dt']}  (days open: {summary['days_open']})\n" +
            f"Last Update: {summary['status_last_update_dt']}  (days since: {summary['days_since_update']})\n" +
            f"CR Number: {summary['RTN_CR_No'] if summary['RTN_CR_No'] else 'None'}  |  Has CR? {summary['has_cr_number']}\n" +
            (f"⚠️  Stale reason: {summary['stale_reason']}\n" if summary['stale_reason'] else "") +
            f"Last note: {summary['status_last_msg'][:300] if summary['status_last_msg'] else '—'}\n" +
            "—"*68 + "\n```"
        )

        # history block
        st.subheader("🧾 Update history (latest last)")
        hist = summary["history"]
        if not hist:
            st.write("No timestamped history found.")
        else:
            txt = "\n".join([f"- [{h['ts']}] {h['text']}" for h in hist[-20:]])
            st.markdown("```text\n" + txt + "\n```")

# Footer
st.caption("Built with Streamlit + Firebase · single-ticket console")
