from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# Load and fix the private key formatting
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")

cred = credentials.Certificate(firebase_config)

# Initialize app once
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

st.title("📄 Credit Request Dashboard")

# --- Upload Excel Template ---
st.header("Step 1: Upload Credit Request Template")
uploaded_excel = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"], key="upload_credit_template")

if uploaded_excel:
    # Load Excel
    df_input = pd.read_excel(uploaded_excel)

    # Make sure required columns exist
    required_cols = ['Credit Request Total', 'Customer Number', 'Invoice Number', 'Item Number']
    for col in required_cols:
        if col not in df_input.columns:
            st.error(f"❌ Column '{col}' not found in uploaded file.")
            st.stop()

    # Take the first row as the entry
    df_entry = df_input.iloc[0:1].copy()

    # --- Step 2: Add Ticket Info ---
    st.header("Step 2: Add Ticket Info")
    with st.form("ticket_info_form"):
        sales_rep = st.text_input("👤 Sales Rep", value="")
        status_text = st.text_area("📜 Status Description", height=200)
        submitted = st.form_submit_button("Submit Record")

        if submitted:
            entry = {
                "Credit Request Total": float(df_entry.iloc[0]['Credit Request Total']),
                "Customer Number": str(df_entry.iloc[0]['Customer Number']),
                "Invoice Number": str(df_entry.iloc[0]['Invoice Number']),
                "Item Number": str(df_entry.iloc[0]['Item Number']),
                "Sales Rep": sales_rep,
                "Status": status_text
            }

            ref.push(entry)
            st.success("✅ Record submitted successfully!")
            st.json(entry)
