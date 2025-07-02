from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Streamlit UI ---
st.title("📋 Update Credit Request Status by Ticket Number")

st.header("Step 1: Enter Ticket Number")
ticket_no = st.text_input("🎫 Ticket Number")

if ticket_no:
    data = ref.get()
    matches = {key: val for key, val in data.items() if str(val.get("Ticket Number")) == ticket_no}

    if matches:
        st.success(f"✅ Found {len(matches)} record(s) under Ticket Number: {ticket_no}")

        st.header("Step 2: Update Status")
        status_option = st.selectbox("🔄 Select New Status", [
            "Update", "Credit No & Reason", "In Process", "Submitted to Billing"
        ])
        status_description = st.text_area("📝 Status Description")
        submit_update = st.button("📤 Submit Status Update")

        if submit_update and status_description:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status_entry = f"[{timestamp}] {status_option}: {status_description}"

            count = 0
            for key, val in matches.items():
                current_status = val.get("Status", "")
                new_status = current_status + "\n" + status_entry if current_status else status_entry
                ref.child(key).update({"Status": new_status})
                count += 1

            st.success(f"✅ Status updated for {count} record(s)!")
    else:
        st.warning("⚠️ No records found for that Ticket Number.")
