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
st.title("📄 Credit Request Dashboard")

# Step 1: Upload File
st.header("Step 1: Upload Credit Request Template")
uploaded_file = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)

    # --- Define Expected Columns ---
    expected_cols = [
        'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price',
        'Corrected Unit Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit'
    ]

    for col in expected_cols:
        if col not in df.columns:
            st.error(f"❌ Missing required column: {col}")
            st.stop()

    df_filtered = df[expected_cols].copy()

    # Coerce numeric values
    df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY'], errors='coerce')
    df_filtered['Unit Price'] = pd.to_numeric(df_filtered['Unit Price'], errors='coerce')
    df_filtered['Corrected Unit Price'] = pd.to_numeric(df_filtered['Corrected Unit Price'], errors='coerce')
    df_filtered['Credit Request Total'] = pd.to_numeric(df_filtered['Credit Request Total'], errors='coerce')

    # --- Check for Duplicates in Firebase ---
    existing_data = ref.get()
    existing_pairs = set()

    if existing_data:
        for record in existing_data.values():
            invoice = record.get("Invoice Number")
            item = record.get("Item Number")
            if invoice and item:
                existing_pairs.add((invoice, item))

    inv = df_filtered.at[0, 'Invoice Number']
    item = df_filtered.at[0, 'Item Number']

    if (inv, item) in existing_pairs:
        st.warning("⚠️ Duplicate entry found in Firebase for Invoice + Item Number. Record will not be submitted.")
        st.stop()

    # --- Ticket Info Form ---
    record = df_filtered.iloc[0].to_dict()

    st.header("Step 2: Add Ticket Info")
    with st.form("ticket_entry"):
        ticket_number = st.text_input("🎫 Ticket Number")
        ticket_date = st.date_input("🗕️ Ticket Date", value=datetime.today())
        status = st.text_area("📜 Status / Reason")
        sales_rep = st.text_input("👤 Sales Rep")
        submitted = st.form_submit_button("Submit Record")

        if submitted:
            record["Ticket Number"] = ticket_number
            record["Date"] = ticket_date.strftime("%Y-%m-%d")
            record["Status"] = status
            record["Sales Rep"] = sales_rep
            record["Record ID"] = f"{ticket_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

            try:
                ref.push(record)
                st.success("✅ Record successfully submitted to Firebase!")
                st.json(record)
            except Exception as e:
                st.error(f"🔥 Submission failed: {e}")
