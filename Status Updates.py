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
st.title("📋 Update Credit Request Status")

st.header("Step 1: Enter Any of the Following")
search_input = st.text_input("🔎 Ticket Number, Invoice Number, Item Number, or Invoice+Item (e.g. 123456|ABC789)")

if search_input:
    data = ref.get()
    search_input = search_input.strip().lower()
    matches = {}
    source = ""

    for key, record in data.items():
        ticket = str(record.get("Ticket Number", "")).strip().lower()
        invoice = str(record.get("Invoice Number", "")).strip().lower()
        item = str(record.get("Item Number", "")).strip().lower()
        status = str(record.get("Status", "")).strip().lower()

        # Match by Ticket Number
        if search_input == ticket:
            matches[key] = record
            source = "Ticket Number"
        # Match by Invoice Number
        elif search_input == invoice:
            matches[key] = record
            source = "Invoice Number"
        # Match by Item Number
        elif search_input == item:
            matches[key] = record
            source = "Item Number"
        # Match by Invoice + Item pair (format: invoice|item)
        elif "|" in search_input:
            parts = search_input.split("|")
            if len(parts) == 2 and invoice == parts[0].strip() and item == parts[1].strip():
                matches[key] = record
                source = "Invoice + Item Pair"
        # Fallback: Search inside Status text
        elif search_input in status:
            matches[key] = record
            source = "Status field (partial match)"

    if matches:
        st.success(f"✅ Found {len(matches)} record(s) using {source}.")

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
        st.warning("⚠️ No records found using any of the search methods.")
