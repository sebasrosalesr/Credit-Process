from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import sqlite3
import time, streamlit as st

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL_SEC = 30 * 60       # 30 min
MAX_ATTEMPTS    = 5
LOCKOUT_SEC     = 60            # 1 min cooldown

def check_password():
    now = time.time()
    # init state
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    # active session timeout
    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL_SEC:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

    # lockout window after too many failures
    if now < st.session_state["locked_until"]:
        st.error("Too many attempts. Try again in a minute.")
        st.stop()

    st.title("🔒 Private Access")
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
            st.error("❌ Incorrect password")
            st.stop()
    st.stop()

# Gate the app
if not check_password():
    st.stop()


# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- SQLite DB for checking duplicates locally ---
db_path = "credits.db"
conn = sqlite3.connect(db_path)

# --- Load Firebase data ---
st.header("🛠️ Edit Existing Records")
data = ref.get()
records = []

if data:
    for key, record in data.items():
        record['firebase_key'] = key
        records.append(record)

df_records = pd.DataFrame(records)

# --- Search UI ---
search_type = st.selectbox("Search by", ["Ticket Number", "Invoice + Item", "Invoice Only", "Item Only"])

results = pd.DataFrame()
if search_type == "Ticket Number":
    ticket = st.text_input("Enter Ticket Number").strip().lower()
    results = df_records[df_records['Ticket Number'].astype(str).str.strip().str.lower() == ticket]
elif search_type == "Invoice + Item":
    invoice = st.text_input("Invoice Number").strip().lower()
    item = st.text_input("Item Number").strip().lower()
    results = df_records[
        (df_records['Invoice Number'].astype(str).str.strip().str.lower() == invoice) &
        (df_records['Item Number'].astype(str).str.strip().str.lower() == item)
    ]
elif search_type == "Invoice Only":
    invoice = st.text_input("Invoice Number").strip().lower()
    results = df_records[df_records['Invoice Number'].astype(str).str.strip().str.lower() == invoice]
elif search_type == "Item Only":
    item = st.text_input("Item Number").strip().lower()
    results = df_records[df_records['Item Number'].astype(str).str.strip().str.lower() == item]

# --- Edit All Matching Records ---
if not results.empty:
    st.write(f"🔍 Found {len(results)} matching record(s):")

    editable_fields = [
        "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
        "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
        "Reason for Credit", "Requested By", "Sales Rep", "Status",
        "Ticket Number", "Unit Price", "Type"
    ]

    for idx, row in results.iterrows():
        with st.expander(f"📄 Record {idx} — Invoice: {row.get('Invoice Number')} | Item: {row.get('Item Number')}"):
            st.write("🧾 Current Record:")
            st.json(row.to_dict())

            updated_data = {}
            for field in editable_fields:
                default = str(row.get(field, ""))
                updated_data[field] = st.text_input(f"{field} (Record {idx})", value=default, key=f"{field}_{idx}")

            if st.button(f"💾 Save Changes for Record {idx}"):
                firebase_key = row['firebase_key']
                try:
                    ref.child(firebase_key).update(updated_data)
                    st.success(f"✅ Record {idx} updated successfully.")
                except Exception as e:
                    st.error(f"❌ Failed to update record {idx}: {e}")
else:
    if search_type:
        st.info("No matching records found.")

# Optional logout button:
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()
