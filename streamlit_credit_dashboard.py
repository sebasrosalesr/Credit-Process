import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
import json

# --- Load Firebase credentials ---
firebase_config = {key: st.secrets["firebase"][key] for key in st.secrets["firebase"].keys()}
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

st.title("📄 Credit Request Dashboard")

# --- Upload Excel Template ---
st.header("Step 1: Upload Credit Request Template")
uploaded_excel = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

if uploaded_excel:
    # Load Excel
    df_input = pd.read_excel(uploaded_excel)

    # Schema
    columns = [
        'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
        'Extended Correct Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit', 'Sales Rep', 'Status', 'Ticket Number'
    ]
    required_cols = [
        'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price',
        'Corrected Unit Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit', 'Sales Rep'
    ]

    # Clean
    df_filtered = df_input[required_cols].copy()
    df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY'], errors='coerce')
    df_filtered['Unit Price'] = pd.to_numeric(df_filtered['Unit Price'], errors='coerce')
    df_filtered['Corrected Unit Price'] = pd.to_numeric(df_filtered['Corrected Unit Price'], errors='coerce')
    df_filtered['Extended Correct Price'] = (
        df_filtered['Unit Price'] * df_filtered['QTY']
        - df_filtered['Corrected Unit Price'] * df_filtered['QTY']
    )
    df_filtered['Date'] = pd.NaT
    df_filtered['Status'] = ''
    df_filtered['Ticket Number'] = ''

    df_main_structure = df_filtered[columns].copy()

    # --- Form UI ---
    st.header("Step 3: Add Ticket Info")
    with st.form("credit_form"):
        ticket_number = st.text_input("🎫 Ticket Number", value="")
        ticket_date = st.date_input("🗕️ Ticket Date", value=datetime.today())
        sales_rep = st.text_input("🧑‍💼 Sales Rep", value="")
        status_text = st.text_area("📝 Status Description", height=200)
        submitted = st.form_submit_button("Submit Record")

    if submitted:
        df_main_structure.at[0, 'Ticket Number'] = ticket_number
        df_main_structure.at[0, 'Date'] = pd.to_datetime(ticket_date).date()
        df_main_structure.at[0, 'Sales Rep'] = sales_rep
        df_main_structure.at[0, 'Status'] = status_text

        # Push to Firebase
        ref.push(df_main_structure.iloc[0].to_dict())
        st.success("✅ Record submitted successfully!")


