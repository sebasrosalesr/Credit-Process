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
db_path = "credits.db"  # Replace with your actual DB path
conn = sqlite3.connect(db_path)

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

    # --- Check for Duplicates (from SQLite DB if available) ---
    try:
        existing = pd.read_sql_query("SELECT `Invoice Number`, `Item Number` FROM credits", conn)
        existing_pairs = set(zip(existing['Invoice Number'], existing['Item Number']))
    except Exception as e:
        existing_pairs = set()

    # --- Step 2: Add Ticket Info ---
    st.header("Step 2: Add Ticket Info")
    with st.form("ticket_entry"):
        ticket_number = st.text_input("🎫 Ticket Number")
        ticket_date = st.date_input("📅 Ticket Date", value=datetime.today())
        status = st.text_area("📜 Status / Reason")
        sales_rep = st.text_input("👤 Sales Rep")
        submitted = st.form_submit_button("Submit Record")

        if submitted:
            count = 0
            for index, row in df_filtered.iterrows():
                inv = row['Invoice Number']
                item = row['Item Number']

                if (inv, item) in existing_pairs:
                    st.warning(f"⚠️ Skipped duplicate: Invoice {inv}, Item {item}")
                    continue

                record = row.to_dict()
                record["Ticket Number"] = ticket_number
                record["Date"] = ticket_date.strftime("%Y-%m-%d")
                record["Status"] = status
                record["Sales Rep"] = sales_rep
                record["Record ID"] = f"{ticket_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{count}"

                try:
                    ref.push(record)
                    count += 1
                except Exception as e:
                    st.error(f"🔥 Submission failed for Invoice {inv}, Item {item}: {e}")

            if count:
                st.success(f"✅ {count} record(s) submitted to Firebase!")
