# reminders_app.py
# --- FORCE DARK MODE FOR THIS APP ONLY ---
dark_css = """
<style>
body {
    background-color: #0E1117 !important;
    color: white !important;
}
[class^="st-"] {
    color: white !important;
}
</style>
"""
import streamlit as st
st.markdown(dark_css, unsafe_allow_html=True)


import os
import io
import json
import time
import sqlite3
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st


# ====================== FIX #1: Safe page icon ======================
st.set_page_config(
    page_title="Reminders",
    page_icon="⏰",        # single emoji or short string only!
    layout="centered"
)

# ====================== FIX #2: Writable directory ======================
DATA_DIR = "/tmp/remindtwin_data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "reminders.db")
MARKER_PATH = os.path.join(DATA_DIR, "last_export.json")

# ====================== FIX #3: Bulletproof timezone ======================
try:
    EOD_TZ = ZoneInfo("America/Indiana/Indianapolis")
except Exception:
    EOD_TZ = ZoneInfo("US/Eastern")   # works everywhere

EOD_CUTOFF = dtime(23, 0)  # 11 PM local

# ====================== PASSWORD ======================
APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", "test123"))

def check_password():
    if st.session_state.get("auth_ok"):
        return True
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

if not check_password():
    st.stop()

with st.sidebar:
    if st.button("Logout"):
        st.session_state.clear()
        st.rerun()

# ====================== HEADER ======================
st.title("Reminder – Personal Task OS")
st.caption("Zero cloud • Daily export • No data loss")

# ====================== DATABASE ======================
def init_db():
    with sqlite3.connect(DB_PATH, timeout=30) as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                due_at TEXT NOT NULL,
                ticket TEXT NOT NULL,
                note TEXT,
                done INTEGER NOT NULL DEFAULT 0
            );
        """)
init_db()

def now_utc():
    return datetime.now(timezone.utc)

def add_reminder(ticket, note, hours):
    due = (now_utc() + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc().isoformat(), due, ticket.strip(), note.strip())
        )

def fetch_open():
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done=0 ORDER BY due_at",
            con
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["due_at"]     = pd.to_datetime(df["due_at"], utc=True)
    return df

def mark_done(rid):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))

def snooze(rid, hours):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT due_at FROM reminders WHERE id=?", (rid,))
        row = cur.fetchone()
        if row is None:
            return
        due = pd.to_datetime(row[0], utc=True) + pd.Timedelta(hours=hours)
        con.execute("UPDATE reminders SET due_at=? WHERE id=?", (due.isoformat(), rid))

# ====================== ADD FORM ======================
with st.form("add", clear_on_submit=True):
    st.subheader("New Reminder")
    ticket = st.text_input("Ticket / Ref*")
    note   = st.text_area("Note (optional)", height=80)
    hrs    = st.selectbox("Remind in", ["4 hours", "24 hours", "48 hours", "Custom"], index=1)
    if hrs == "Custom":
        hrs = st.number_input("Hours", 1, 336, 8)
    else:
        hrs = {"4 hours": 4, "24 hours": 24, "48 hours": 48}[hrs]
    if st.form_submit_button("Add"):
        if not ticket.strip():
            st.error("Ticket required")
        else:
            add_reminder(ticket, note, hrs)
            st.success(f"Added {ticket} → due in {hrs}h")
            st.balloons()
            time.sleep(1)
            st.rerun()

# ====================== OPEN REMINDERS ======================
st.divider()
st.subheader("Open Reminders")
df = fetch_open()
if df.empty:
    st.success("All clear!")
else:
    now = pd.Timestamp.now(tz="UTC")
    for _, r in df.iterrows():
        hrs_left = (r.due_at - now).total_seconds() / 3600
        color = "red" if hrs_left < 0 else "orange" if hrs_left < 4 else "green"
        label = f"overdue {abs(hrs_left):.0f}h" if hrs_left < 0 else f"{hrs_left:.0f}h left"

        with st.container(border=True):
            c1, c2, c3 = st.columns([0.4, 0.2, 0.4])
            with c1:
                st.markdown(f"**{r.ticket}**")
                if r.note:
                    st.caption(r.note)
            with c2:
                st.markdown(
                    f"<small style='color:{color}'>{label}</small>",
                    unsafe_allow_html=True
                )
            with c3:
                if st.button("Done", key=f"d{r.id}"):
                    mark_done(r.id)
                    st.rerun()
                if st.button("Snooze 4h", key=f"s4{r.id}"):
                    snooze(r.id, 4)
                    st.rerun()
                if st.button("Snooze 24h", key=f"s24{r.id}"):
                    snooze(r.id, 24)
                    st.rerun()

# ====================== DONE REMINDERS ======================
st.divider()
st.subheader("Completed Reminders ✔️")

def fetch_done():
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done=1 ORDER BY due_at DESC",
            con
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["due_at"]     = pd.to_datetime(df["due_at"], utc=True)
    return df

df_done = fetch_done()

if df_done.empty:
    st.caption("No completed reminders yet.")
else:
    # Small local date just for this section
    today_local_done = datetime.now(EOD_TZ).date().isoformat()

    # Show summary table
    st.dataframe(
        df_done[["ticket", "note", "created_at", "due_at"]],
        use_container_width=True,
        hide_index=True
    )

    # Export Done → CSV
    done_csv = df_done.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download Completed (CSV)",
        data=done_csv,
        file_name=f"completed_{today_local_done}.csv",
        mime="text/csv"
    )

    # Delete all completed reminders
    if st.button("🗑️ Clear Completed Reminders"):
        try:
            with sqlite3.connect(DB_PATH) as con:
                con.execute("DELETE FROM reminders WHERE done=1;")
            st.success("Completed reminders cleared.")
            st.rerun()
        except Exception as e:
            st.error(f"Error clearing completed reminders: {e}")

# ====================== EXPORT / IMPORT ======================
st.divider()
today_local = datetime.now(EOD_TZ).date().isoformat()
if datetime.now(EOD_TZ).time() >= EOD_CUTOFF:
    st.info(f"Time for daily export – {today_local}")

c1, c2 = st.columns(2)

# ---- SQL DUMP EXPORT (fixed) ----
with c1:
    with sqlite3.connect(DB_PATH) as con:
        sql_dump_bytes = "\n".join(con.iterdump()).encode("utf-8")

    st.download_button(
        label="⬇️ Download SQL dump",
        data=sql_dump_bytes,
        file_name=f"reminders_{today_local}.sql",
        mime="application/sql"
    )

# ---- CSV of open items ----
with c2:
    csv_data = (df if not df.empty else pd.DataFrame(columns=["id","created_at","due_at","ticket","note"])) \
        .to_csv(index=False).encode("utf-8")

    st.download_button(
        label="⬇️ Download open reminders (CSV)",
        data=csv_data,
        file_name=f"open_{today_local}.csv",
        mime="text/csv"
    )

st.markdown("---")

# ---- SQL DUMP IMPORT / RESTORE ----
st.subheader("Restore from SQL dump")
st.caption("⚠️ This will overwrite the current reminders database.")

uploaded_sql = st.file_uploader(
    "Upload a .sql dump exported from this app",
    type=["sql"],
    accept_multiple_files=False
)

if uploaded_sql is not None:
    restore_now = st.button("Restore database from dump (irreversible)")
    if restore_now:
        try:
            sql_text = uploaded_sql.read().decode("utf-8")

            with sqlite3.connect(DB_PATH) as con:
                # Drop existing table(s) and recreate from dump
                con.executescript("DROP TABLE IF EXISTS reminders;")
                con.executescript(sql_text)

            st.success("Database restored from dump. Reloading…")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Restore failed: {e}")

st.caption("Built by Sebastian • Local-only • Zero data loss")
