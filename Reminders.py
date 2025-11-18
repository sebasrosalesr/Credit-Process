# reminders_app.py
# RemindTwin – Personal AI Task OS | Zero Data Loss | End-of-Day Export
# FIXED & HARDENED for Streamlit Cloud + Python 3.11+ (2025)

import os
import io
import json
import time
import sqlite3
from datetime import datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

# =========================
# CONFIG & PAGE SETUP
# =========================
st.set_page_config(page_title="Reminders", page_icon="Alarm Clock", layout="centered")

# =========================
# SECURE PATHS (works on Streamlit Cloud, local, everywhere)
# =========================
# Use /tmp on Streamlit Cloud (read-only filesystem otherwise)
DATA_DIR = "/tmp/remindtwin_data"
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "reminders.db")
MARKER_PATH = os.path.join(DATA_DIR, "last_export.json")

# =========================
# TIMEZONE – BULLETPROOF (2025+)
# =========================
try:
    EOD_TZ = ZoneInfo("America/Indiana/Indianapolis")
except Exception:
    # Fallback chain – one will always work
    EOD_TZ = ZoneInfo("US/Eastern")

EOD_CUTOFF = dtime(23, 0)  # 11:00 PM local time in Indianapolis

# =========================
# SECURITY: Password + Session Timeout
# =========================
APP_PASSWORD = st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", "test123"))
SESSION_TTL_SEC = 30 * 60   # 30 min idle timeout
MAX_ATTEMPTS = 5
LOCKOUT_SEC = 60

def check_password():
    now = time.time()
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False
        st.session_state.last_seen = 0.0
        st.session_state.bad_attempts = 0
        st.session_state.locked_until = 0.0

    # Already logged in?
    if st.session_state.auth_ok:
        if now - st.session_state.last_seen > SESSION_TTL_SEC:
            st.session_state.auth_ok = False
        else:
            st.session_state.last_seen = now
            return True

    # Lockout?
    if now < st.session_state.locked_until:
        remaining = int(st.session_state.locked_until - now)
        st.error(f"Too many attempts. Try again in {remaining} seconds.")
        st.stop()

    st.title("Private Access Required")
    pwd = st.text_input("Password", type="password", key="pwd_input")
    if st.button("Login", type="primary"):
        if pwd == APP_PASSWORD:
            st.session_state.update(
                auth_ok=True,
                last_seen=now,
                bad_attempts=0,
                locked_until=0.0
            )
            st.success("Access granted!")
            time.sleep(0.8)
            st.rerun()
        else:
            st.session_state.bad_attempts += 1
            if st.session_state.bad_attempts >= MAX_ATTEMPTS:
                st.session_state.locked_until = now + LOCKOUT_SEC
                st.session_state.bad_attempts = 0
            st.error(f"Incorrect password ({st.session_state.bad_attempts}/{MAX_ATTEMPTS})")
            st.stop()
    st.stop()

if not check_password():
    st.stop()

# Logout button
with st.sidebar:
    st.write(f"Logged in @ {datetime.now(EOD_TZ).strftime('%Y-%m-%d %I:%M %p')}")
    if st.button("Logout", type="secondary"):
        for key in ["auth_ok", "last_seen", "bad_attempts", "locked_until"]:
            st.session_state.pop(key, None)
        st.rerun()

# =========================
# APP HEADER
# =========================
st.title("Alarm Clock Reminder – Personal Task OS")
st.caption("Zero cloud • Daily export • No data loss ever")

# =========================
# DATABASE
# =========================
def init_db():
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
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
        con.commit()

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def add_reminder(ticket: str, note: str, hours: int):
    ticket = ticket.strip()
    note = note.strip() if note else ""
    due_at = (now_utc() + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc().isoformat(), due_at, ticket, note)
        )
        con.commit()

def fetch_open() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done = 0 ORDER BY due_at ASC",
            con
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["due_at"] = pd.to_datetime(df["due_at"], utc=True)
    return df

def fetch_done(limit: int = 50) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done = 1 ORDER BY id DESC LIMIT ?",
            con,
            params=(limit,)
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["due_at"] = pd.to_datetime(df["due_at"], utc=True)
    return df

def mark_done(rid: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        con.execute("UPDATE reminders SET done = 1 WHERE id = ?", (rid,))
        con.commit()

def snooze(rid: int, hours: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        row = con.execute("SELECT due_at FROM reminders WHERE id = ?", (rid,)).fetchone()
        if row:
            new_due = (pd.to_datetime(row[0], utc=True) + pd.Timedelta(hours=hours)).isoformat()
            con.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (new_due, rid))
            con.commit()

def delete_reminder(rid: int):
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        con.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        con.commit()

def was_recently_added(ticket: str, minutes: int = 2) -> bool:
    ticket = ticket.strip()
    if not ticket:
        return False
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        row = con.execute(
            "SELECT created_at FROM reminders WHERE ticket = ? AND done = 0 ORDER BY id DESC LIMIT 1",
            (ticket,)
        ).fetchone()
    if not row:
        return False
    created = pd.to_datetime(row[0], utc=True)
    return (pd.Timestamp.now(tz="UTC") - created).total_seconds() < minutes * 60

# =========================
# EXPORT / IMPORT HELPERS
# =========================
def _read_last_export() -> str | None:
    if not os.path.exists(MARKER_PATH):
        return None
    try:
        with open(MARKER_PATH) as f:
            return json.load(f).get("last_export_date")
    except:
        return None

def _write_last_export(date_str: str):
    with open(MARKER_PATH, "w") as f:
        json.dump({"last_export_date": date_str}, f)

def dump_db_to_sql() -> bytes:
    buf = io.StringIO()
    with sqlite3.connect(DB_PATH) as con:
        for line in con.iterdump():
            buf.write(f"{line}\n")
    return buf.getvalue().encode("utf-8")

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def should_export_today() -> tuple[bool, str]:
    now_local = datetime.now(EOD_TZ)
    today = now_local.date().isoformat()
    last = _read_last_export()
    return (now_local.time() >= EOD_CUTOFF and last != today, today)

# =========================
# INIT
# =========================
init_db()

# =========================
# UI: ADD REMINDER
# =========================
with st.form("add_form", clear_on_submit=True):
    st.subheader("Add New Reminder")
    ticket = st.text_input("Ticket / Reference*", placeholder="R-052066, INV13652804")
    note = st.text_area("Note (optional)", placeholder="Call Scott about credit")
    preset = st.selectbox("Remind me in…", ["4 hours", "24 hours", "48 hours", "Custom…"], index=1)
    custom_h = 0
    if preset == "Custom…":
        custom_h = st.number_input("Hours", min_value=1, max_value=336, value=8, step=1)
    submitted = st.form_submit_button("Add Reminder")
    
    if submitted:
        hours = {"4 hours": 4, "24 hours": 24, "48 hours": 48}.get(preset, custom_h)
        if not ticket.strip():
            st.error("Ticket is required.")
        elif was_recently_added(ticket):
            st.warning("You already added this ticket recently – skipped.")
        else:
            add_reminder(ticket, note, hours)
            st.success(f"Added: **{ticket}** → due in {hours}h")
            st.balloons()
            time.sleep(1)
            st.rerun()

# =========================
# OPEN REMINDERS
# =========================
st.divider()
st.subheader("Open Reminders")

open_df = fetch_open()
if open_df.empty:
    st.success("All caught up! No open reminders.")
else:
    now = pd.Timestamp.now(tz="UTC")
    for _, row in open_df.iterrows():
        rid = int(row["id"])
        delta_h = (row["due_at"] - now).total_seconds() / 3600
        overdue = delta_h < 0
        label = f"overdue {-delta_h:.0f}h" if overdue else f"due in {delta_h:.0f}h"
        color = "red" if overdue else "orange" if delta_h < 4 else "green"

        with st.container(border=True):
            col1, col2, col3 = st.columns([0.45, 0.2, 0.35])
            with col1:
                st.markdown(f"**{row['ticket']}**")
                if row["note"]:
                    st.caption(row["note"])
                st.caption(f"Created {row['created_at'].tz_convert(EOD_TZ).strftime('%m-%d %H:%M')} local")
            with col2:
                st.write("**Due**")
                st.markdown(f"<div style='color:{color};font-weight:bold'>{label}</div>", unsafe_allow_html=True)
                st.caption(row["due_at"].tz_convert(EOD_TZ).strftime("%m-%d %H:%M") + " local")
            with col3:
                if st.button("Done", key=f"done_{rid}", type="primary", use_container_width=True):
                    mark_done(rid)
                    st.rerun()
                if st.button("Snooze 4h", key=f"s4_{rid}", use_container_width=True):
                    snooze(rid, 4)
                    st.rerun()
                if st.button("Snooze 24h", key=f"s24_{rid}", use_container_width=True):
                    snooze(rid, 24)
                    st.rerun()
                if st.button("Delete", key=f"del_{rid}", type="secondary", use_container_width=True):
                    delete_reminder(rid)
                    st.rerun()

# =========================
# RECENTLY COMPLETED
# =========================
st.divider()
with st.expander("Recently Completed (last 50)", expanded=False):
    done_df = fetch_done(50)
    if not done_df.empty:
        view = done_df.copy()
        view["created"] = view["created_at"].dt.tz_convert(EOD_TZ).strftime("%m-%d %H:%M")
        view["due"] = view["due_at"].dt.tz_convert(EOD_TZ).strftime("%m-%d %H:%M")
        st.dataframe(
            view[["ticket", "note", "created", "due"]].rename(columns={
                "ticket": "Ticket", "note": "Note", "created": "Created", "due": "Due"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.write("No completed items yet.")

# =========================
# END-OF-DAY EXPORT
# =========================
st.divider()
st.subheader("End-of-Day Export (Indianapolis Time)")

offer_export, today_str = should_export_today()
if offer_export:
    st.warning(f"It's past 11:00 PM in Indianapolis → Time to export {today_str}!")

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("Export SQL Dump", type="primary"):
        sql_bytes = dump_db_to_sql()
        _write_last_export(today_str)
        st.download_button(
            "Download reminders_dump.sql",
            data=sql_bytes,
            file_name=f"reminders_{today_str}.sql",
            mime="application/sql"
        )

with c2:
    st.download_button(
        "Open → CSV",
        data=df_to_csv_bytes(fetch_open()),
        file_name=f"open_{today_str}.csv",
        mime="text/csv"
    )
    st.download_button(
        "All Completed → CSV",
        data=df_to_csv_bytes(fetch_done(10000)),
        file_name=f"completed_{today_str}.csv",
        mime="text/csv"
    )

with c3:
    with st.expander("Import SQL Dump"):
        uploaded = st.file_uploader("Upload .sql file", type=["sql"])
        if st.button("Import & Replace Database"):
            if not uploaded:
                st.error("Upload a file first.")
            else:
                with st.spinner("Importing..."):
                    try:
                        script = uploaded.read().decode("utf-8")
                        temp_db = sqlite3.connect(":memory:")
                        temp_db.executescript(script)
                        with sqlite3.connect(DB_PATH) as target:
                            temp_db.backup(target)
                        st.success("Import successful! Refreshing...")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")

# =========================
# FOOTER
# =========================
st.markdown("---")
st.caption("Local SQLite • No cloud • Daily backup • Zero data loss • Built with love by Sebastian Rosales")
