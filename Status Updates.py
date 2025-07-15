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
st.set_page_config(page_title="Bulk Status Update", layout="wide")
st.title("📋 Bulk Update Credit Request Status")

st.header("Step 1: Search Records")
search_input = st.text_input("🔍 Ticket Number, Invoice Number, Item Number, or Invoice|Item pair")

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

        if search_input == ticket:
            matches[key] = record
            source = "Ticket Number"
        elif search_input == invoice:
            matches[key] = record
            source = "Invoice Number"
        elif search_input == item:
            matches[key] = record
            source = "Item Number"
        elif "|" in search_input:
            parts = search_input.split("|")
            if len(parts) == 2 and invoice == parts[0].strip() and item == parts[1].strip():
                matches[key] = record
                source = "Invoice + Item Pair"
        elif search_input in status:
            matches[key] = record
            source = "Status field (partial match)"

    if matches:
        st.success(f"✅ Found {len(matches)} record(s) using {source}.")

        # Optional: display results before updating
        df_preview = pd.DataFrame.from_dict(matches, orient="index")
        st.dataframe(df_preview)

        st.header("Step 2: Apply Bulk Status Update")
        status_option = st.selectbox("🔄 New Status", [
            "Update", "Credit No & Reason", "In Process", "Submitted to Billing"
        ])
        status_description = st.text_area("📝 Status Description")

        if st.button("📤 Apply Status Update to All"):
            if not status_description.strip():
                st.warning("⚠️ Please enter a status description.")
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                status_entry = f"[{timestamp}] {status_option}: {status_description}"

                count = 0
                for key, val in matches.items():
                    current_status = val.get("Status", "")
                    new_status = current_status + "\n" + status_entry if current_status else status_entry
                    ref.child(key).update({"Status": new_status})
                    count += 1

                st.success(f"✅ Updated {count} record(s) with new status.")
    else:
        st.warning("⚠️ No records matched your search input.")
