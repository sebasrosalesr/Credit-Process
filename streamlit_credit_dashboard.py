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

    # Keep only required columns
    df_filtered = df[expected_cols].copy()

    # Coerce numeric values
    df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY'], errors='coerce')
    df_filtered['Unit Price'] = pd.to_numeric(df_filtered['Unit Price'], errors='coerce')
    df_filtered['Corrected Unit Price'] = pd.to_numeric(df_filtered['Corrected Unit Price'], errors='coerce')
    df_filtered['Credit Request Total'] = pd.to_numeric(df_filtered['Credit Request Total'], errors='coerce')

    # Use only the first row
    record = df_filtered.iloc[0].to_dict()

    # Step 2: Add Ticket Info
    st.header("Step 2: Add Ticket Info")
    with st.form("ticket_entry"):
        ticket_number = st.text_input("🎫 Ticket Number")
        ticket_date = st.date_input("📅 Ticket Date", value=datetime.today())
        status = st.text_area("📝 Status / Reason")
        sales_rep = st.text_input("👤 Sales Rep")

        submitted = st.form_submit_button("Submit Record")

        if submitted:
            # Finalize and clean record
            record["Ticket Number"] = ticket_number
            record["Date"] = ticket_date.strftime("%Y-%m-%d")
            record["Status"] = status
            record["Sales Rep"] = sales_rep

            # ✅ Add unique Record ID for easier lookup
            unique_id = f"{ticket_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            record["Record ID"] = unique_id

            # Upload to Firebase
            try:
                ref.push(record)
                st.success("✅ Record successfully submitted to Firebase!")
                st.json(record)  # Show record for confirmation
            except Exception as e:
                st.error(f"🔥 Submission failed: {e}")
