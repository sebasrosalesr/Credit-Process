# streamlit_followups.py
import streamlit as st
from datetime import datetime, timedelta, timezone
import uuid, pandas as pd

import firebase_admin
from firebase_admin import credentials, db

st.set_page_config(page_title="Follow-ups", page_icon="⏰", layout="centered")
st.title("⏰ Personal Follow-up Reminders")

# --- Firebase init ---
@st.cache_resource
def init_fb():
    cfg = dict(st.secrets["firebase"])
    if "private_key" in cfg and "\\n" in cfg["private_key"]:
        cfg["private_key"] = cfg["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(cfg)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            "databaseURL": "https://creditapp-tm-default-rtdb.firebaseio.com/"
        })
    return True

init_fb()
ref = db.reference("followups")  # separate path

# --- Create form ---
with st.form("new_fu"):
    title = st.text_input("Ticket / Note (free text)", placeholder="R-046037 — check CR number")
    remind_24 = st.checkbox("Remind in 24 hours", value=True)
    remind_48 = st.checkbox("Also remind in 48 hours")
    notify_via = st.selectbox("Notify via", ["teams_webhook", "email", "none"], index=0)
    teams_webhook = st.text_input("Teams incoming webhook (if using Teams)", "")
    email_to = st.text_input("Email to notify (if using Email)", "")
    submit = st.form_submit_button("Create reminder", type="primary")

if submit:
    if not title.strip():
        st.error("Please enter a Ticket/Note.")
    elif notify_via == "teams_webhook" and not teams_webhook.strip():
        st.error("Add a Teams webhook or choose another notify method.")
    elif notify_via == "email" and not email_to.strip():
        st.error("Add an email or choose another notify method.")
    elif not (remind_24 or remind_48):
        st.error("Pick at least one reminder (24h or 48h).")
    else:
        now = datetime.now(timezone.utc)
        sched = []
        if remind_24: sched.append((now + timedelta(hours=24)).isoformat())
        if remind_48: sched.append((now + timedelta(hours=48)).isoformat())
        rid = str(uuid.uuid4())
        payload = {
            "id": rid,
            "title": title.strip(),
            "created_at": now.isoformat(),
            "schedule": sched,            # list of ISO datetimes (each one is a send)
            "notify_via": notify_via,     # teams_webhook | email | none
            "teams_webhook": teams_webhook.strip() or None,
            "email_to": email_to.strip() or None,
            "sent": [],                   # list of ISO datetimes already sent
            "status": "active"            # active | done | cancelled
        }
        ref.child(rid).set(payload)
        st.success("Reminder(s) created.")

# --- List & quick actions ---
data = ref.get() or {}
rows = list(data.values())
if rows:
    df = pd.DataFrame(rows)
    df["next_due"] = None
    for i, r in df.iterrows():
        pending = [d for d in (r["schedule"] or []) if d not in (r["sent"] or [])]
        if pending:
            df.at[i, "next_due"] = min(pending)
    show = df.sort_values(["status","next_due"], na_position="last")
    st.subheader("📅 My reminders")
    st.dataframe(show[["title","status","next_due","notify_via","email_to"]].reset_index(drop=True))

    # Cancel / mark done
    with st.expander("Manage reminders"):
        for r in rows:
            cols = st.columns([6,1,1])
            cols[0].markdown(f"**{r['title']}** · status: `{r['status']}`")
            if cols[1].button("Done", key=f"done_{r['id']}"):
                ref.child(r["id"]).update({"status":"done"})
                st.experimental_rerun()
            if cols[2].button("Cancel", key=f"cancel_{r['id']}"):
                ref.child(r["id"]).update({"status":"cancelled"})
                st.experimental_rerun()
else:
    st.info("No reminders yet. Add one above.")
