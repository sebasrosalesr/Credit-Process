# reminders_app.py
import os
import io
import json
import time
import sqlite3
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

import os
os.makedirs("/tmp/app_data", exist_ok=True)          # ← fixes read-only FS
st.set_page_config(page_icon="rocket")               # ← single emoji only!

# Bulletproof timezone (covers 90% of the crashes)
from zoneinfo import ZoneInfo
try:
    TZ = ZoneInfo("America/Indiana/Indianapolis")
except:
    TZ = ZoneInfo("US/Eastern")

# ====================== FIX #1: Safe page icon ======================
st.set_page_config(
    page_title="Reminders",
    page_icon="clock",        # single emoji or short string only!
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
except:
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

def now_utc(): return datetime.now(timezone.utc)

def add_reminder(ticket, note, hours):
    due = (now_utc() + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc().isoformat(), due, ticket.strip(), note.strip())
        )

def fetch_open():
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query("SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done=0 ORDER BY due_at", con)
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
        due = pd.to_datetime(cur.fetchone()[0], utc=True) + pd.Timedelta(hours=hours)
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
        hrs = {"4 hours":4, "24 hours":24, "48 hours":48}[hrs]
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
                if r.note: st.caption(r.note)
            with c2:
                st.markdown(f"<small style='color:{color}'>{label}</small>", unsafe_allow_html=True)
            with c3:
                if st.button("Done", key=f"d{r.id}"):
                    mark_done(r.id); st.rerun()
                if st.button("Snooze 4h", key=f"s4{r.id}"):
                    snooze(r.id, 4); st.rerun()
                if st.button("Snooze 24h", key=f"s24{r.id}"):
                    snooze(r.id, 24); st.rerun()

# ====================== EXPORT ======================
st.divider()
today_local = datetime.now(EOD_TZ).date().isoformat()
if datetime.now(EOD_TZ).time() >= EOD_CUTOFF:
    st.info(f"Time for daily export – {today_local}")

c1, c2 = st.columns(2)
with c1:
    if st.button("Export SQL Dump"):
        with sqlite3.connect(DB_PATH) as con:
            sql = "\n".join(con.iterdump()).encode()
        st.download_button("Download reminders.sql", sql, f"reminders_{today_local}.sql")
with c2:
    st.download_button("Open → CSV", df.to_csv(index=False).encode(), f"open_{today_local}.csv")

st.caption("Built by Sebastian • Local-only • Zero data loss")
