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

st.header("Step 1: Identify Entry")
invoice_no = st.text_input("📄 Invoice Number")
item_no = st.text_input("🧾 Item Number")
ticket_no = st.text_input("🎫 Ticket Number (Optional)")

if invoice_no and item_no:
    # Search for matching record
    data = ref.get()
    match_key = None
    match_record = None
    for key, val in data.items():
        if str(val.get("Invoice Number")) == invoice_no and str(val.get("Item Number")) == item_no:
            if not ticket_no or str(val.get("Ticket Number")) == ticket_no:
                match_key = key
                match_record = val
                break

    if match_record:
        st.success("✅ Match found! You can now update the status.")

        st.header("Step 2: Update Status")
        status_option = st.selectbox("🔄 Select New Status", [
            "Update", "Credit No & Reason", "In Process", "Submitted to Billing"
        ])
        status_description = st.text_area("📝 Status Description")
        submit_update = st.button("📤 Submit Status Update")

        if submit_update and status_description:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status_entry = f"[{timestamp}] {status_option}: {status_description}"

            # Append to existing status or initialize
            current_status = match_record.get("Status", "")
            new_status = current_status + "\n" + status_entry if current_status else status_entry

            # Update record
            ref.child(match_key).update({"Status": new_status})
            st.success("✅ Status updated successfully!")
    else:
        st.warning("⚠️ No matching record found. Check the Invoice and Item Number.")
