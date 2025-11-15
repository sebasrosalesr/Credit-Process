# reminders_app.py
# RemindTwin – Personal AI Task OS | Zero Data Loss | End-of-Day Export
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
# SECURITY: Password + Session Timeout
# =========================
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL_SEC = 30 * 60  # 30 minutes idle timeout
MAX_ATTEMPTS = 5
LOCKOUT_SEC = 60

def check_password():
    now = time.time()
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    # Active session check
    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL_SEC:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

    # Lockout
    if now < st.session_state["locked_until"]:
        st.error("Too many attempts. Try again in a minute.")
        st.stop()

    st.title("Private Access")
    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.update(auth_ok=True, last_seen=now, bad_attempts=0)
            st.rerun()
        else:
            st.session_state["bad_attempts"] += 1
            if st.session_state["bad_attempts"] >= MAX_ATTEMPTS:
                st.session_state["locked_until"] = now + LOCKOUT_SEC
                st.session_state["bad_attempts"] = 0
            st.error("Incorrect password")
            st.stop()
    st.stop()

if not check_password():
    st.stop()

# Logout
with st.sidebar:
    if st.button("Logout"):
        st.session_state["auth_ok"] = False
        st.rerun()

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="RemindTwin", page_icon="⏰", layout="centered")
st.title("⏰ RemindTwin – Personal AI Task OS")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "reminders.db")
MARKER_PATH = os.path.join(DATA_DIR, "last_export.json")

EOD_TZ = ZoneInfo("America/Indiana/Indianapolis")
EOD_CUTOFF = dtime(23, 0)  # 11:00 PM local

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

def now_utc():
    return datetime.now(timezone.utc).isoformat()

def add_reminder(ticket: str, note: str, hours: int):
    ticket = ticket.strip()
    note = note.strip()
    due_at = (datetime.fromisoformat(now_utc()[:-6]) + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH, timeout=30.0) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc(), due_at, ticket, note)
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
            con, params=(limit,)
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
            current = pd.to_datetime(row[0], utc=True)
            new_due = (current + pd.Timedelta(hours=hours)).isoformat()
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
# EXPORT / IMPORT
# =========================
def _read_last_export():
    if not os.path.exists(MARKER_PATH):
        return None
    try:
        with open(MARKER_PATH, "r") as f:
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
# UI: ADD REMINDER
# =========================
init_db()

with st.form("add_reminder_form", clear_on_submit=True):
    st.subheader("Add Reminder")
    ticket = st.text_input("Ticket / Reference", placeholder="R-052066, INV13652804")
    note = st.text_area("Note (optional)", placeholder="Call Scott re: credit")
    preset = st.selectbox("Remind in…", ["4 hours", "24 hours", "48 hours", "Custom…"], index=1)
    custom_h = st.number_input("Custom hours", min_value=1, max_value=336, value=4, step=1) if preset == "Custom…" else 0
    submitted = st.form_submit_button("➕ Add")

    if submitted:
        hours = {"4 hours": 4, "24 hours": 24, "48 hours": 48}.get(preset, int(custom_h))
        if not ticket.strip():
            st.error("Ticket required.")
        elif was_recently_added(ticket):
            st.warning("Duplicate skipped.")
        else:
            add_reminder(ticket, note, hours)
            st.success(f"Reminder added: **{ticket}** in **{hours}h**")
            st.rerun()

# =========================
# UI: OPEN REMINDERS
# =========================
st.divider()
st.subheader("Open Reminders")
open_df = fetch_open()
if open_df.empty:
    st.info("No open reminders. You're all caught up!")
else:
    now = pd.Timestamp.now(tz="UTC")
    for _, row in open_df.iterrows():
        rid = int(row["id"])
        delta_h = (row["due_at"] - now).total_seconds() / 3600
        due_label = f"due in {delta_h:.0f}h" if delta_h >= 0 else f"overdue {abs(delta_h):.0f}h"
        color = "green" if delta_h >= 0 else "red"

        with st.container(border=True):
            c1, c2, c3 = st.columns([0.5, 0.2, 0.3])
            with c1:
                st.markdown(f"**{row['ticket']}**")
                if row["note"]:
                    st.caption(row["note"])
                st.caption(f"Created: {row['created_at'].tz_convert('UTC').strftime('%m-%d %H:%M')} UTC")
            with c2:
                st.write("**Due**")
                st.markdown(f"<span style='color:{color}; font-weight:600'>{due_label}</span>", unsafe_allow_html=True)
                st.caption(row["due_at"].tz_convert('UTC').strftime('%m-%d %H:%M') + " UTC")
            with c3:
                if st.button("Done", key=f"done_{rid}"):
                    mark_done(rid); st.rerun()
                if st.button("Snooze 4h", key=f"s4_{rid}"):
                    snooze(rid, 4); st.rerun()
                if st.button("Snooze 24h", key=f"s24_{rid}"):
                    snooze(rid, 24); st.rerun()
                if st.button("Snooze 48h", key=f"s48_{rid}"):
                    snooze(rid, 48); st.rerun()
                cs_col1, cs_col2 = st.columns([0.6, 0.4])
                with cs_col1:
                    cs_h = st.number_input("hrs", min_value=1, max_value=336, value=12, key=f"cs_h_{rid}")
                with cs_col2:
                    if st.button("Snooze", key=f"cs_{rid}"):
                        snooze(rid, cs_h); st.rerun()
                if st.button("Delete", key=f"del_{rid}"):
                    delete_reminder(rid); st.rerun()

# =========================
# UI: COMPLETED
# =========================
st.divider()
st.subheader("Recently Completed")
done_df = fetch_done(50)
if not done_df.empty:
    view = done_df.copy()
    view["created_at"] = view["created_at"].dt.strftime("%m-%d %H:%M")
    view["due_at"] = view["due_at"].dt.strftime("%m-%d %H:%M")
    st.dataframe(
        view[["ticket", "note", "created_at", "due_at"]].rename(columns={
            "ticket": "Ticket",
            "note": "Note",
            "created_at": "Created",
            "due_at": "Due"
        }),
        use_container_width=True,
        hide_index=True
    )
else:
    st.caption("No completed reminders.")

# =========================
# END-OF-DAY EXPORT
# =========================
st.divider()
st.subheader("End-of-Day Export (Indianapolis Time)")

def render_exports():
    offer, today = should_export_today()
    if offer:
        st.info(f"It's past 11:00 PM in Indianapolis. Export today ({today})?")

    c1, c2, c3 = st.columns([0.34, 0.33, 0.33])

    # Export SQL
    with c1:
        if st.button("Export SQL Dump"):
            sql_data = dump_db_to_sql()
            _write_last_export(today)
            st.download_button(
                "Download reminders_dump.sql",
                data=sql_data,
                file_name=f"reminders_{today}.sql",
                mime="application/sql"
            )

    # Export CSVs
    with c2:
        st.download_button(
            "Open (CSV)",
            data=df_to_csv_bytes(fetch_open()),
            file_name=f"open_{today}.csv",
            mime="text/csv"
        )
        st.download_button(
            "Completed (CSV)",
            data=df_to_csv_bytes(fetch_done(10000)),
            file_name=f"completed_{today}.csv",
            mime="text/csv"
        )

    # Import SQL
    with c3:
        with st.expander("Import SQL Dump"):
            uploaded = st.file_uploader("Upload .sql", type=["sql"], key="import_sql")
            if uploaded and st.button("Import Now"):
                try:
                    script = uploaded.read().decode("utf-8")
                with st.spinner("Importing safely..."):
                    # Step 1: Load dump into in-memory DB
                    temp_db = sqlite3.connect(":memory:")
                    temp_db.executescript(script)
                    temp_db.commit()

                    # Step 2: Use SQLite backup API (atomic, no locks)
                        with sqlite3.connect(DB_PATH) as target_db:
                           temp_db.backup(target_db)
                           target_db.commit()

                    temp_db.close()
                st.success("Import complete! App refreshed.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {str(e)}")
      

# =========================
# FOOTER
# =========================
st.markdown("<hr>", unsafe_allow_html=True)
st.caption("Local SQLite • No cloud • Daily export • Zero data loss • Built by Sebastian Rosales")
