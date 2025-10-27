# reminders.py
import sqlite3, time
from datetime import datetime, timedelta, timezone
from contextlib import closing

import pandas as pd
import streamlit as st

# ==========
# Storage: local SQLite (no Firebase, no cloud config)
# ==========

DB_PATH = "reminders.db"

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as con, con, con.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            due_at TEXT NOT NULL,
            ticket TEXT NOT NULL,
            note TEXT,
            done INTEGER NOT NULL DEFAULT 0
        );""")

def now_utc():
    return datetime.now(timezone.utc)

def add_reminder(ticket: str, note: str, due_delta_hours: int):
    due_at = now_utc() + timedelta(hours=due_delta_hours)
    with closing(sqlite3.connect(DB_PATH)) as con, con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc().isoformat(), due_at.isoformat(), ticket.strip(), note.strip())
        )

def fetch_open():
    with closing(sqlite3.connect(DB_PATH)) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note, done FROM reminders WHERE done=0 ORDER BY due_at ASC",
            con
        )
    for col in ("created_at", "due_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df

def fetch_done(limit=50):
    with closing(sqlite3.connect(DB_PATH)) as con:
        df = pd.read_sql_query(
            f"SELECT id, created_at, due_at, ticket, note, done FROM reminders WHERE done=1 ORDER BY id DESC LIMIT {int(limit)}",
            con
        )
    for col in ("created_at", "due_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df

def mark_done(reminder_id: int):
    with closing(sqlite3.connect(DB_PATH)) as con, con, con.cursor() as cur:
        cur.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))

def snooze(reminder_id: int, hours: int):
    with closing(sqlite3.connect(DB_PATH)) as con, con, con.cursor() as cur:
        cur.execute("SELECT due_at FROM reminders WHERE id=?", (reminder_id,))
        row = cur.fetchone()
        if not row: return
        current_due = datetime.fromisoformat(row[0])
        new_due = current_due + timedelta(hours=hours)
        cur.execute("UPDATE reminders SET due_at=? WHERE id=?", (new_due.isoformat(), reminder_id))

# ==========
# UI
# ==========
st.set_page_config(page_title="Personal Follow-ups", page_icon="⏰", layout="centered")
st.title("⏰ Personal Follow-up Reminders")

init_db()

with st.form("new"):
    st.subheader("Add a reminder")
    ticket = st.text_input("Ticket / Reference (free text)", placeholder="R-052066 or INV13652804 or 'Call Scott re: CR'")
    note = st.text_area("Note (optional)", placeholder="Short context or next action")
    preset = st.selectbox("Remind me in…", ["24 hours", "48 hours", "Custom…"])
    custom_hours = 0
    if preset == "Custom…":
        custom_hours = st.number_input("Custom hours", min_value=1, max_value=24*14, value=72, step=1)
    submit = st.form_submit_button("Add reminder", type="primary")

    if submit:
        if not ticket.strip():
            st.error("Ticket/Reference is required.")
        else:
            hours = 24 if preset == "24 hours" else 48 if preset == "48 hours" else int(custom_hours)
            add_reminder(ticket, note, hours)
            st.success("Reminder added.")
            st.rerun()

st.divider()
st.subheader("Open reminders")

open_df = fetch_open()
if open_df.empty:
    st.info("No open reminders yet.")
else:
    # Compute status columns
    now = now_utc()
    open_df["in_hours"] = (open_df["due_at"] - now).dt.total_seconds() / 3600
    open_df["status"] = open_df["in_hours"].apply(
        lambda h: "OVERDUE" if h < 0 else ("Soon" if h <= 24 else "Scheduled")
    )

    # Color badges & quick actions
    for _, row in open_df.iterrows():
        is_overdue = row["in_hours"] < 0
        colA, colB, colC, colD = st.columns([3, 3, 2, 3], vertical_alignment="center")

        with colA:
            st.markdown(
                f"**{row['ticket']}**  \n"
                f"<span style='color:#666'>{row['note'] or ''}</span>",
                unsafe_allow_html=True
            )
        with colB:
            due_str = row["due_at"].astimezone().strftime("%b %d, %I:%M %p")
            if is_overdue:
                st.markdown(f"**Due:** ⛔️ **OVERDUE** (was {due_str})")
            else:
                st.markdown(f"**Due:** {due_str}")

        with colC:
            badge = "🔴 OVERDUE" if is_overdue else ("🟡 due ≤24h" if row["in_hours"] <= 24 else "🟢 scheduled")
            st.markdown(badge)

        with colD:
            b1, b2, b3 = st.columns(3)
            if b1.button("Done", key=f"done_{row['id']}"):
                mark_done(int(row["id"]))
                st.toast(f"Marked done: {row['ticket']}")
                time.sleep(0.2)
                st.rerun()
            if b2.button("Snooze +24h", key=f"s24_{row['id']}"):
                snooze(int(row["id"]), 24)
                st.toast("Snoozed +24h")
                time.sleep(0.2)
                st.rerun()
            if b3.button("Snooze +48h", key=f"s48_{row['id']}"):
                snooze(int(row["id"]), 48)
                st.toast("Snoozed +48h")
                time.sleep(0.2)
                st.rerun()

    st.caption("Tip: items turn 🟡 when due within 24h, 🔴 after they pass their due time.")

st.divider()
with st.expander("Completed (last 50)"):
    done_df = fetch_done(50)
    if done_df.empty:
        st.write("—")
    else:
        done_df = done_df.assign(
            created_at_local=done_df["created_at"].dt.tz_convert(None),
            due_at_local=done_df["due_at"].dt.tz_convert(None)
        )[["id", "ticket", "note", "created_at_local", "due_at_local"]]
        done_df.columns = ["ID", "Ticket", "Note", "Created", "Original Due"]
        st.dataframe(done_df, use_container_width=True, hide_index=True)

# ========== Optional: export ==========
st.download_button(
    "Download open reminders (CSV)",
    data=fetch_open().to_csv(index=False),
    file_name="open_reminders.csv",
    mime="text/csv",
)
