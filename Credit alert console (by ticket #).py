# app.py
import re
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse

import numpy as np
import pandas as pd
import streamlit as st

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, db

# -----------------------------
# UI CONFIG
# -----------------------------
st.set_page_config(page_title="Credit Ticket Console", page_icon="🎫", layout="wide")
st.title("🎫 Credit Ticket Console")
st.caption("Search any ticket, see last update, staleness, CR number, and full history.")

# =========================
# Firebase init (from secrets)
# =========================
@st.cache_resource(show_spinner=False)
def init_firebase():
    """
    Expects in .streamlit/secrets.toml:
    [firebase]
    type="service_account"
    project_id="..."
    private_key="-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
    client_email="..."
    firebase_db_url="https://<your-db>.firebasedatabase.app/"
    """
    cfg = dict(st.secrets["firebase"])
    db_url = cfg.pop("firebase_db_url")
    # normalize private key newlines
    if "private_key" in cfg and "\\n" in cfg["private_key"]:
        cfg["private_key"] = cfg["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(cfg)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"databaseURL": db_url})
    return True

init_firebase()

# =========================
# Data load
# =========================
@st.cache_data(show_spinner=True, ttl=60)
def load_credit_requests() -> pd.DataFrame:
    ref = db.reference("credit_requests")
    raw = ref.get() or {}
    rows = []
    # expected columns (safe fill with None)
    columns = [
        "Corrected Unit Price","Credit Request Total","Credit Type","Customer Number","Date",
        "Extended Price","Invoice Number","Issue Type","Item Number","QTY","Reason for Credit",
        "Record ID","Requested By","Sales Rep","Status","Ticket Number","Unit Price","Type","RTN_CR_No"
    ]
    for value in raw.values():
        row = {c: value.get(c, None) for c in columns}
        rows.append(row)
    df = pd.DataFrame(rows)
    return df

df = load_credit_requests()

# =========================
# Helper functions (from your notebook)
# =========================
def parse_any_dt(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return pd.NaT
    try:
        return pd.to_datetime(dtparse(str(s), fuzzy=True))
    except Exception:
        return pd.NaT

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
    if any(k in text for k in ["denied", "no credit warranted", "rejected"]):
        return "Denied"
    if any(k in text for k in ["approved", "submitted", "credit issued", "posted"]):
        return "Approved/Submitted"
    if any(k in text for k in ["resolved", "closing", "closed"]):
        return "Resolved/Closing"
    if any(k in text for k in ["wip", "in process", "pending", "delay", "delayed"]):
        return "In Process"
    return "Unknown"

# Policy thresholds (your chosen values)
STALE_UPDATE_DAYS = 21
STALE_OPEN_DAYS   = 30

def summarize_row(row: pd.Series):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    status = str(row.get("Status", "") or "")
    req_dt = parse_any_dt(row.get("Date"))
    last_dt, last_msg, n_updates = extract_status_last(status)
    if pd.isna(last_dt):
        last_dt = req_dt
    days_open = int((now - req_dt).days) if pd.notna(req_dt) else None
    dsu = int((now - last_dt).days) if pd.notna(last_dt) else None
    state = classify_state(status, last_msg)
    rtn = row.get("RTN_CR_No", None)
    has_cr = False if rtn is None else (str(rtn).strip() != "")
    is_closedish = (state in ["Resolved/Closing", "Approved/Submitted", "Denied"]) or \
                   (re.search(r"\bclosed\b", status, flags=re.I) is not None)
    # stale reason
    stale_reason = None
    if not is_closedish:
        if dsu is not None and dsu >= STALE_UPDATE_DAYS:
            stale_reason = f"No status update in ≥{STALE_UPDATE_DAYS} days"
        elif days_open is not None and days_open >= STALE_OPEN_DAYS:
            stale_reason = f"Open for ≥{STALE_OPEN_DAYS} days"
        elif not has_cr:
            stale_reason = "Missing CR Number"
    # severity
    if is_closedish:
        alert = "GREEN"
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
        "status_num_updates": n_updates,
        "status_state": state,
        "days_open": days_open,
        "days_since_update": dsu,
        "RTN_CR_No": rtn,
        "has_cr_number": has_cr,
        "stale_reason": stale_reason,
        "alert": alert,
        "closing_soon": bool(re.search(r"close in\s+\d+\s+days", status, flags=re.I)),
        "Status_full": status
    }

def check_ticket(df: pd.DataFrame, ticket_number: str = None, record_id: str = None):
    if ticket_number:
        sub = df[df["Ticket Number"].astype(str) == str(ticket_number)]
    elif record_id:
        sub = df[df["Record ID"].astype(str) == str(record_id)]
    else:
        raise ValueError("Provide ticket_number or record_id")

    if sub.empty:
        return None, []

    if len(sub) > 1:
        temp = sub.copy()
        temp["_req_dt"] = temp["Date"].apply(parse_any_dt)
        temp["_last_dt"] = temp["Status"].apply(lambda s: extract_status_last(str(s))[0] or pd.NaT)
        temp = temp.sort_values(["_last_dt","_req_dt"], ascending=[False, False])
        row = temp.iloc[0]
    else:
        row = sub.iloc[0]

    summary = summarize_row(row)
    history = extract_status_history(summary["Status_full"])
    return summary, history

# =========================
# Sidebar: search + refresh
# =========================
with st.sidebar:
    st.header("Search")
    tnum = st.text_input("Ticket Number (e.g., R-046037)", value="", help="Preferred lookup key")
    rid  = st.text_input("Record ID (optional)", value="")
    col_ref = st.columns(2)
    do_search = col_ref[0].button("Search", type="primary", use_container_width=True)
    do_refresh = col_ref[1].button("↻ Refresh data", use_container_width=True)
    if do_refresh:
        load_credit_requests.clear()  # clear cache
        df = load_credit_requests()
        st.success("Data refreshed.")

# =========================
# Main: results
# =========================
if do_search:
    if not tnum and not rid:
        st.warning("Enter a Ticket Number or Record ID.")
    else:
        summary, history = check_ticket(df, ticket_number=tnum if tnum else None, record_id=rid if rid else None)
        if not summary:
            st.error("Ticket not found.")
        else:
            # Header + badges
            a_color = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(summary["alert"], "⚪️")
            st.subheader(f"{a_color} {summary['Ticket Number']}  ·  {summary['Record ID']}")
            c1, c2, c3, c4 = st.columns([1.2,1,1,1.2])
            c1.metric("State", summary["status_state"])
            c2.metric("Days open", summary["days_open"])
            c3.metric("Days since update", summary["days_since_update"])
            c4.metric("CR Number", summary["RTN_CR_No"] if summary["RTN_CR_No"] else "—")

            st.write(f"**Requester:** {summary['Requested By'] or '—'}   |   **Sales Rep:** {summary['Sales Rep'] or '—'}")
            if summary["stale_reason"]:
                st.warning(f"Stale reason: {summary['stale_reason']}")
            if summary["closing_soon"]:
                st.info("⏳ Closing soon flag detected in Status text.")

            st.markdown(f"**Opened:** {summary['request_dt']}")
            st.markdown(f"**Last Update:** {summary['status_last_update_dt']}")
            st.markdown(f"**Last note:** {summary['status_last_msg'] if summary['status_last_msg'] else '—'}")

            with st.expander("🧾 Full update history (latest last)", expanded=False):
                if history:
                    hist_df = pd.DataFrame(history)
                    hist_df.rename(columns={"ts": "Timestamp", "text": "Message"}, inplace=True)
                    st.dataframe(hist_df, use_container_width=True, hide_index=True)
                else:
                    st.write("No timestamped history found.")

# =========================
# Table: tickets needing attention (YELLOW/RED)
# =========================
@st.cache_data(show_spinner=False, ttl=60)
def build_alerts_table(df: pd.DataFrame):
    # compute summaries for all rows
    if df.empty:
        return pd.DataFrame()
    summaries = [summarize_row(r) for _, r in df.iterrows()]
    s_df = pd.DataFrame(summaries)
    closed_mask = s_df["status_state"].isin(["Resolved/Closing", "Approved/Submitted", "Denied"]) | \
                  s_df["Status_full"].str.contains(r"\bclosed\b", case=False, na=False)
    attention = s_df.loc[(~closed_mask) & (s_df["alert"].isin(["YELLOW","RED"]))].copy()
    attention = attention.sort_values(["alert","days_since_update","days_open"], ascending=[True, False, False])
    return attention

st.markdown("---")
st.subheader("⚠️ Tickets Needing Attention (YELLOW / RED)")
att = build_alerts_table(df)
if att.empty:
    st.success("No tickets require attention right now.")
else:
    show_cols = ["Ticket Number","Requested By","Issue Type","status_state","days_since_update","days_open",
                 "stale_reason","has_cr_number","RTN_CR_No","alert"]
    st.dataframe(att[show_cols], use_container_width=True, hide_index=True)
    csv = att[show_cols].to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name="ticket_alerts.csv", mime="text/csv", use_container_width=True)
