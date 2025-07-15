from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import sqlite3

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
st.header("🛠️ Edit Existing Record")
data = ref.get()
records = []

if data:
    for key, record in data.items():
        record['firebase_key'] = key
        records.append(record)

df_records = pd.DataFrame(records)

# --- Search UI ---
search_type = st.selectbox("Search by", ["Ticket Number", "Invoice + Item", "Invoice Only", "Item Only"])

if search_type == "Ticket Number":
    ticket = st.text_input("Enter Ticket Number")
    results = df_records[df_records['Ticket Number'].astype(str).str.lower() == ticket.lower()]
elif search_type == "Invoice + Item":
    invoice = st.text_input("Invoice Number")
    item = st.text_input("Item Number")
    results = df_records[
        (df_records['Invoice Number'].astype(str).str.lower() == invoice.lower()) &
        (df_records['Item Number'].astype(str).str.lower() == item.lower())
    ]
elif search_type == "Invoice Only":
    invoice = st.text_input("Invoice Number")
    results = df_records[df_records['Invoice Number'].astype(str).str.lower() == invoice.lower()]
elif search_type == "Item Only":
    item = st.text_input("Item Number")
    results = df_records[df_records['Item Number'].astype(str).str.lower() == item.lower()]
else:
    results = pd.DataFrame()

# --- Edit Selected Record ---
if not results.empty:
    selected_index = st.selectbox("Select record to edit", results.index.tolist())
    selected_row = results.loc[selected_index]
    st.write("🔍 Current Record:")
    st.json(selected_row.to_dict())

    # --- Editable Fields ---
    st.write("✏️ Edit Fields")
    updated_data = {}
    editable_fields = [
        "Corrected Unit Price", "Credit Request Total", "Credit Type", "Customer Number", "Date",
        "Extended Price", "Invoice Number", "Issue Type", "Item Number", "QTY",
        "Reason for Credit", "Requested By", "Sales Rep", "Status",
        "Ticket Number", "Unit Price", "Type"
    ]
    for field in editable_fields:
        default = str(selected_row.get(field, ""))
        updated_data[field] = st.text_input(field, value=default)

    # --- Update Firebase ---
    if st.button("💾 Save Changes"):
        firebase_key = selected_row['firebase_key']
        try:
            ref.child(firebase_key).update(updated_data)
            st.success("✅ Record updated successfully.")
        except Exception as e:
            st.error(f"❌ Failed to update record: {e}")
else:
    if search_type:
        st.info("No matching records found.")
