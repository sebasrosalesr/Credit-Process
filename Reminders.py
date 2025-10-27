# reminders.py
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

DB_PATH = "reminders.db"

# =========================
# DB helpers (simple, safe)
# =========================
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

def now_utc_dt():
    return datetime.now(timezone.utc)

def add_reminder(ticket: str, note: str, hours: int):
    ticket = (ticket or "").strip()
    note = (note or "").strip()
    due_at = (now_utc_dt() + timedelta(hours=hours)).isoformat()
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO reminders (created_at, due_at, ticket, note, done) VALUES (?, ?, ?, ?, 0)",
            (now_utc_dt().isoformat(), due_at, ticket, note),
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
        df["due_at"]     = pd.to_datetime(df["due_at"],     utc=True, errors="coerce")
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
        df["due_at"]     = pd.to_datetime(df["due_at"],     utc=True, errors="coerce")
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
        new_due = (current_due + pd.Timedelta(hours=int(hours))).isoformat()
        con.execute("UPDATE reminders SET due_at=? WHERE id=?", (new_due, int(reminder_id)))
        con.commit()

def delete_reminder(reminder_id: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM reminders WHERE id=?", (int(reminder_id),))
        con.commit()

def was_recently_added(ticket: str, minutes=2) -> bool:
    """Prevent accidental double-adds of the same ticket within N minutes."""
    ticket = (ticket or "").strip()
    if not ticket:
        return False
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT created_at FROM reminders WHERE ticket=? AND done=0 ORDER BY id DESC LIMIT 1",
            (ticket,),
        ).fetchone()
    if not row:
        return False
    created = pd.to_datetime(row[0], utc=True, errors="coerce")
    return (pd.Timestamp.now(tz="UTC") - created).total_seconds() < minutes * 60


# =========
#   UI
# =========
st.set_page_config(page_title="Personal Follow-ups", page_icon="⏰", layout="centered")
st.title("⏰ Personal Follow-up Reminders")

init_db()

# ------------- New reminder form -------------
with st.form("new"):
    st.subheader("Add a reminder")
    ticket = st.text_input(
        "Ticket / Reference (free text)",
        placeholder="R-052066, INV13652804, 'Call Scott re: CR', …"
    )
    note = st.text_area("Note (optional)", placeholder="Short context or next action")

    preset = st.selectbox(
        "Remind me in…",
        ["4 hours", "24 hours", "48 hours", "Custom…"],
        index=1  # default to 24h
    )
    custom_hours = st.number_input(
        "Custom hours",
        min_value=1, max_value=24*14, value=4, step=1,
        help="Only used when 'Custom…' is selected"
    ) if preset == "Custom…" else 0

    submitted = st.form_submit_button("➕ Add reminder")
    if submitted:
        # Determine hours from preset
        if preset == "4 hours":
            hours = 4
        elif preset == "24 hours":
            hours = 24
        elif preset == "48 hours":
            hours = 48
        else:
            hours = int(custom_hours)

        if not ticket.strip():
            st.error("Please enter a ticket / reference.")
        elif hours <= 0:
            st.error("Hours must be > 0.")
        elif was_recently_added(ticket):
            st.warning("Looks like you just added this ticket. Skipping duplicate.")
        else:
            add_reminder(ticket, note, hours)
            st.success(f"Reminder added for **{ticket.strip()}** in **{hours}** hour(s).")
            st.rerun()

st.divider()
st.subheader("Open reminders")

open_df = fetch_open()
if open_df.empty:
    st.info("No open reminders. 🎉")
else:
    now = pd.Timestamp.now(tz="UTC")
    for _, row in open_df.iterrows():
        rid       = int(row["id"])
        ticket    = row["ticket"]
        note      = row.get("note") or ""
        created_at = row["created_at"]
        due_at     = row["due_at"]

        # Time delta
        delta_hours = (due_at - now).total_seconds() / 3600.0
        due_label = f"due in {abs(delta_hours):.0f}h" if delta_hours >= 0 else f"⚠️ overdue {abs(delta_hours):.0f}h"
        due_color = "green" if delta_hours >= 0 else "red"

        with st.container(border=True):
            top_cols = st.columns([0.55, 0.20, 0.25])

            # Left: ticket + note
            with top_cols[0]:
                st.markdown(f"**{ticket}**")
                if note:
                    st.caption(note)
                st.caption(f"Created: {created_at.tz_convert('UTC').strftime('%Y-%m-%d %H:%M UTC')}")

            # Middle: due info
            with top_cols[1]:
                st.write("**Due**")
                st.markdown(
                    f"<span style='color:{due_color}; font-weight:600'>{due_label}</span>",
                    unsafe_allow_html=True
                )
                st.caption(due_at.tz_convert('UTC').strftime('%Y-%m-%d %H:%M UTC'))

            # Right: actions
            with top_cols[2]:
                btn_done = st.button("✅ Done", key=f"done_{rid}")
                b4  = st.button("🕓 Snooze 4h",  key=f"s4_{rid}")
                b24 = st.button("🕘 Snooze 24h", key=f"s24_{rid}")
                b48 = st.button("🕘 Snooze 48h", key=f"s48_{rid}")

                cs_cols = st.columns([0.6, 0.4])
                with cs_cols[0]:
                    cs_val = st.number_input(
                        "hrs", min_value=1, max_value=24*14, value=12, step=1, key=f"cshrs_{rid}"
                    )
                with cs_cols[1]:
                    bcs = st.button("Snooze", key=f"cs_{rid}")

                bdel = st.button("🗑️ Delete", key=f"del_{rid}")

                # Handlers
                if btn_done:
                    mark_done(rid)
                    st.rerun()
                if b4:
                    snooze(rid, 4)
                    st.rerun()
                if b24:
                    snooze(rid, 24)
                    st.rerun()
                if b48:
                    snooze(rid, 48)
                    st.rerun()
                if bcs:
                    snooze(rid, int(cs_val))
                    st.rerun()
                if bdel:
                    delete_reminder(rid)
                    st.rerun()

st.divider()
st.subheader("Recently completed")

done_df = fetch_done(limit=50)
if done_df.empty:
    st.caption("No completed reminders yet.")
else:
    view = done_df.copy()
    view["created_at"] = (
        pd.to_datetime(view["created_at"], utc=True, errors="coerce")
          .dt.tz_convert("UTC")
          .dt.strftime("%Y-%m-%d %H:%M")
    )
    view["due_at"] = (
        pd.to_datetime(view["due_at"], utc=True, errors="coerce")
          .dt.tz_convert("UTC")
          .dt.strftime("%Y-%m-%d %H:%M")
    )

    # Show last 50 completed
    st.dataframe(
        view[["id", "ticket", "note", "created_at", "due_at"]]
            .rename(columns={
                "id": "ID",
                "ticket": "Ticket / Ref",
                "note": "Note",
                "created_at": "Created (UTC)",
                "due_at": "Original Due (UTC)",
            }),
        use_container_width=True,
        hide_index=True,
    )
    # Optional: prune older completed items (keep the latest 50)
    colc1, colc2 = st.columns([0.35, 0.65])
    with colc1:
        if st.button("🧹 Clear older completed (keep latest 50)"):
            with sqlite3.connect(DB_PATH) as con:
                con.execute("""
                    DELETE FROM reminders
                    WHERE done = 1
                      AND id NOT IN (
                        SELECT id FROM reminders
                        WHERE done = 1
                        ORDER BY id DESC
                        LIMIT 50
                      )
                """)
                con.commit()
            st.success("Old completed reminders cleared.")
            st.rerun()

# -------- Footer --------
st.markdown("<hr/>", unsafe_allow_html=True)
st.caption(
    "Local SQLite storage • No external services • "
    "Use the buttons to mark done, snooze, or delete. "
    "Timestamps shown in UTC."
)
