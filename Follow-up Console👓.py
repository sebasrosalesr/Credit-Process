# streamlit_followups.py
import re
import pandas as pd
from datetime import datetime, timezone
from dateutil.parser import parse as dtparse
import streamlit as st

# 🔧 NEW: Firebase Admin imports
import firebase_admin
from firebase_admin import credentials, db

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

# 🔧 NEW: robust date parse used in loader
def safe_parse_force_string(x):
    try:
        return pd.to_datetime(dtparse(str(x), fuzzy=True))
    except Exception:
        return pd.NaT

# 🔧 NEW: Load df from Firebase if not already present
@st.cache_data(show_spinner=True, ttl=120)
def load_data():
    cols = [
        "Record ID","Ticket Number","Requested By","Sales Rep",
        "Issue Type","Date","Status","RTN_CR_No"
    ]
    ref = db.reference("credit_requests")
    raw = ref.get() or {}
    df_ = pd.DataFrame([{c: v.get(c, None) for c in cols} for v in raw.values()])
    df_["Date"] = df_["Date"].apply(safe_parse_force_string)
    df_ = df_.dropna(subset=["Date"]).copy()
    # make datetimes naive to avoid tz math issues downstream
    if pd.api.types.is_datetime64_any_dtype(df_["Date"]):
        try:
            df_["Date"] = df_["Date"].dt.tz_localize(None)
        except Exception:
            pass
    return df_

if "df" not in st.session_state:
    st.session_state["df"] = load_data()

# =========================
# Expect required columns
# =========================
required_cols = {
    "Date","Status","Record ID","Ticket Number","Requested By",
    "Sales Rep","Issue Type","RTN_CR_No"
}
missing = [c for c in required_cols if c not in st.session_state.get("df", pd.DataFrame()).columns]

if not missing:
    df = st.session_state["df"].copy()
else:
    st.info("⚠️ DataFrame is missing columns: " + ", ".join(missing))
    st.stop()

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
            "No follow-up required."
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

# ---- Date range UI (defaults = last 3 months) ----
today = pd.Timestamp.today().normalize()
default_start = (today - pd.DateOffset(months=3)).to_pydatetime().date()
default_end   = today.to_pydatetime().date()

c1, c2 = st.columns(2)
with c1:
    ui_start = st.date_input("Start date", value=default_start)
with c2:
    ui_end   = st.date_input("End date", value=default_end)

# Guard: ensure start <= end
if ui_start > ui_end:
    st.error("Start date must be on or before End date.")
    st.stop()

# Convert to pandas Timestamps (inclusive end)
range_start = pd.to_datetime(ui_start)
range_end   = pd.to_datetime(ui_end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

# Ensure Date is datetime and filter
df_range = df.copy()
df_range[DATE_COL] = pd.to_datetime(df_range[DATE_COL], errors="coerce")
mask = (df_range[DATE_COL] >= range_start) & (df_range[DATE_COL] <= range_end)
df_month = df_range.loc[mask].copy()

st.success(f"✅ Loaded {len(df_month)} tickets in range {range_start.date()} → {range_end.date()}")

# ⬇️ CREATE summary (this was missing)
summary = df_month.apply(summarize_row, axis=1, result_type="expand")

# Generate messages
summary[["message_subject", "message_body"]] = summary.apply(
    lambda s: pd.Series(make_followup_or_status_message(s)),
    axis=1
)

# Follow-up flag (same rule)
summary["needs_followup"] = (
    ((~summary["has_cr_number"]) | (summary["days_since_update"].fillna(-1) >= FOLLOWUP_UPDATE_DAYS))
    & ~((summary["status_state"] == "Unknown") & summary["has_cr_number"])
)

# Console-style count
st.caption(f"🔴 Follow-ups to send: {int(summary['needs_followup'].sum())} / {len(summary)}")

# =========================
# Per-ticket rollup + single "Full ticket detail" UI
# =========================

# Collapse to one representative row per ticket.
# If a ticket has multiple lines, we pick the "worst" line to display:
#  - needs_followup lines first
#  - then lines missing CR number
#  - then the largest days_since_update
# ---------- Build per-ticket rollup (one row per Ticket Number) ----------
if summary.empty:
    ticket_view = pd.DataFrame(columns=[
        "Ticket Number","needs_followup_any","any_no_cr","lines_in_range",
        "lines_missing_cr","max_days_since_update","message_subject","message_body","RTN_CR_No","__label__"
    ])
else:
    def _reduce_group(df_t: pd.DataFrame) -> pd.Series:
        needs_any  = bool(df_t["needs_followup"].fillna(False).any())
        any_no_cr  = bool((~df_t["has_cr_number"].fillna(False)).any())
        lines_in   = int(len(df_t))
        lines_miss = int((~df_t["has_cr_number"].fillna(False)).sum())
        dsu_max    = pd.to_numeric(df_t["days_since_update"], errors="coerce").max()

        # Pick a representative line to show:
        # Prefer the one with the biggest days_since_update; fallback to first row.
        dsu_series = pd.to_numeric(df_t["days_since_update"], errors="coerce").fillna(-1)
        rep_idx = dsu_series.idxmax() if not dsu_series.empty else df_t.index[0]
        rep = df_t.loc[rep_idx]

        return pd.Series({
            "needs_followup_any": needs_any,
            "any_no_cr": any_no_cr,
            "lines_in_range": lines_in,
            "lines_missing_cr": lines_miss,
            "max_days_since_update": dsu_max,
            "message_subject": rep.get("message_subject", ""),
            "message_body": rep.get("message_body", ""),
            "RTN_CR_No": rep.get("RTN_CR_No", None)
        })

    ticket_view = (
        summary
        .groupby("Ticket Number", dropna=False)
        .apply(_reduce_group)
        .reset_index()
    )

    # Build readable option labels
    def _label_row(r):
        status = "FOLLOW-UP" if r["needs_followup_any"] else "NO ACTION"
        if r["any_no_cr"]:
            cr_label = f"MISSING ({int(r['lines_missing_cr'])} of {int(r['lines_in_range'])})"
        else:
            cr_label = "OK"
        return f"{r['Ticket Number']} | {status} | CR={cr_label} | lines={int(r['lines_in_range'])}"

    ticket_view["__label__"] = ticket_view.apply(_label_row, axis=1)

# ---------- UI: Full ticket detail ONLY ----------
st.subheader("🔎 Full ticket detail")

if ticket_view.empty:
    st.info("No tickets matched the selected date range.")
else:
    choice = st.selectbox(
        "Pick a ticket to view full lines",
        options=ticket_view["__label__"].tolist(),
        index=0
    )
    sel_row = ticket_view.loc[ticket_view["__label__"] == choice].iloc[0]

    # Subject + Body (your exact message format)
    st.markdown("**Subject**")
    st.code(str(sel_row["message_subject"]), language="text")

    st.markdown("**Body**")
    st.code(str(sel_row["message_body"]), language="text")

    # Helpful ticket-level context
    st.markdown(
        f"- **Lines in range:** {int(sel_row['lines_in_range'])}\n"
        f"- **Lines missing CR:** {int(sel_row['lines_missing_cr'])}\n"
        f"- **Any line needs follow-up:** {'Yes' if sel_row['needs_followup_any'] else 'No'}\n"
        f"- **Any line missing CR:** {'Yes' if sel_row['any_no_cr'] else 'No'}\n"
        f"- **Worst days since update:** "
        f"{int(sel_row['max_days_since_update']) if pd.notna(sel_row['max_days_since_update']) else '—'}"
    )

    # All raw lines for this ticket (optional drilldown)
    with st.expander("All lines for this ticket (raw rows)", expanded=False):
        all_lines = summary.loc[summary["Ticket Number"] == sel_row["Ticket Number"]].copy()
        cols_show = [
            "Record ID","Ticket Number","Issue Type","status_state",
            "RTN_CR_No","has_cr_number","days_since_update",
            "message_subject","message_body","needs_followup"
        ]
        cols_show = [c for c in cols_show if c in all_lines.columns]
        st.dataframe(
            all_lines[cols_show].sort_values("days_since_update", ascending=False),
            use_container_width=True,
            hide_index=True
        )

# Export: per-ticket rollup CSV (one row per ticket)
out_path = "followups_ticket_rollup_{}_to_{}.csv".format(
    range_start.strftime("%Y%m%d"), range_end.strftime("%Y%m%d")
)
csv_bytes = ticket_view.drop(columns=["__label__"], errors="ignore") \
                       .to_csv(index=False, encoding="utf-8-sig")
st.download_button(
    "⬇️ Download per-ticket rollup CSV",
    data=csv_bytes,
    file_name=out_path,
    mime="text/csv"
)
