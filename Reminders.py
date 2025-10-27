# reminders.py
import sqlite3, time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

DB_PATH = "reminders.db"

# -------------------------
# Small compatibility helper
# -------------------------
def safe_rerun():
    """Rerun for any Streamlit version."""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# -------------------------
# DB helpers (simple, safe)
# -------------------------
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            due_at     TEXT NOT NULL,
            ticket     TEXT NOT NULL,
            note       TEXT,
            done       INTEGER NOT NULL DEFAULT 0
        );
        """)
        con.commit()

def now_utc():
    return datetime.now(timezone.utc)

def add_reminder(ticket: str, note: str, hours: int):
    due_at = (now_utc() + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc().isoformat(), due_at, ticket.strip(), (note or "").strip()),
        )
        con.commit()

def fetch_open() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done=0 ORDER BY due_at ASC",
            con,
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["due_at"] = pd.to_datetime(df["due_at"], utc=True, errors="coerce")
    return df

def fetch_done(limit=50) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as con:
        df = pd.read_sql_query(
            "SELECT id, created_at, due_at, ticket, note FROM reminders WHERE done=1 ORDER BY id DESC LIMIT ?",
            con,
            params=(int(limit),),
        )
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["due_at"] = pd.to_datetime(df["due_at"], utc=True, errors="coerce")
    return df

def mark_done(reminder_id: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE reminders SET done=1 WHERE id=?", (int(reminder_id),))
        con.commit()

def snooze(reminder_id: int, hours: int):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT due_at FROM reminders WHERE id=?", (int(reminder_id),)).fetchone()
        if not row:
            return
        current_due = pd.to_datetime(row[0], utc=True, errors="coerce")
        new_due = (current_due + pd.Timedelta(hours=hours)).to_pydatetime().isoformat()
        con.execute("UPDATE reminders SET due_at=? WHERE id=?", (new_due, int(reminder_id)))
        con.commit()

# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="Personal Follow-ups", page_icon="⏰", layout="centered")
st.title("⏰ Personal Follow-up Reminders")

init_db()

# show any queued flash after a rerun
if msg := st.session_state.pop("_flash_msg", None):
    st.success(msg)

with st.form("new"):
    st.subheader("Add a reminder")
    ticket = st.text_input("Ticket / Reference (free text)", placeholder="R-052066, INV13652804, 'Call Scott re: CR', …")
    note = st.text_area("Note (optional)", placeholder="Short context or next action")
    preset = st.selectbox("Remind me in…", ["24 hours", "48 hours", "Custom…"])
    custom_hours = st.number_input("Custom hours", min_value=1, max_value=24*14, value=72, step=1) if preset == "Custom…" else 0
    submitted = st.form_submit_button("➕ Add reminder")
    if submitted:
        # Figure hours
        if preset == "24 hours":
            hours = 24
        elif preset == "48 hours":
            hours = 48
        else:
            hours = int(custom_hours)

        if not ticket.strip():
            st.error("Please enter a ticket / reference.")
        elif hours <= 0:
            st.error("Hours must be > 0.")
        else:
            add_reminder(ticket, note, hours)
            # Persist success across rerun
            st.session_state._flash_msg = f"Reminder added for {ticket.strip()} in {hours} hour(s)."
            safe_rerun()

st.divider()
st.subheader("Open reminders")

open_df = fetch_open()
if open_df.empty:
    st.info("No open reminders. 🎉")
else:
    # Render each reminder with actions
    now = pd.Timestamp.utcnow().tz_localize("UTC")
    for _, row in open_df.iterrows():
        rid   = int(row["id"])
        ticket = row["ticket"]
        note   = row.get("note") or ""
        due_at = row["due_at"]
        created_at = row["created_at"]

        # Δ time (hours)
        delta_hours = (due_at - now).total_seconds() / 3600.0
        due_label = (
            f"due in {abs(delta_hours):.0f}h"
            if delta_hours >= 0
            else f"⚠️ overdue {abs(delta_hours):.0f}h"
        )

        with st.container(border=True):
            top_cols = st.columns([0.55, 0.20, 0.25])
            with top_cols[0]:
                st.markdown(f"**{ticket}**")
                if note:
                    st.caption(note)
                st.caption(f"Created: {created_at.tz_convert('UTC').strftime('%Y-%m-%d %H:%M UTC')}")
            with top_cols[1]:
                st.write("**Due**")
                color = "red" if delta_hours < 0 else "green"
                st.markdown(f"<span style='color:{color}; font-weight:600'>{due_label}</span>", unsafe_allow_html=True)
                st.caption(due_at.tz_convert('UTC').strftime('%Y-%m-%d %H:%M UTC'))
            with top_cols[2]:
                btn_done = st.button("✅ Done", key=f"done_{rid}")
                b24 = st.button("🕘 Snooze 24h", key=f"s24_{rid}")
                b48 = st.button("🕘 Snooze 48h", key=f"s48_{rid}")
                # custom snooze inline
                cs_cols = st.columns([0.6, 0.4])
                with cs_cols[0]:
                    cs_val = st.number_input("hrs", min_value=1, max_value=24*14, value=12, step=1, key=f"cshrs_{rid}")
                with cs_cols[1]:
                    bcs = st.button("Snooze", key=f"cs_{rid}")

                # Handle actions
                if btn_done:
                    mark_done(rid)
                    safe_rerun()
                if b24:
                    snooze(rid, 24)
                    safe_rerun()
                if b48:
                    snooze(rid, 48)
                    safe_rerun()
                if bcs:
                    snooze(rid, int(cs_val))
                    safe_rerun()

st.divider()
st.subheader("Recently completed")
done_df = fetch_done(limit=50)
if done_df.empty:
    st.caption("No completed reminders yet.")
else:
    show = done_df.copy()
    show["created_at"] = show["created_at"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M")
    show["due_at"]     = show["due_at"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(
        show[["id","ticket","note","created_at","due_at"]],
        hide_index=True,
        use_container_width=True,
    )
