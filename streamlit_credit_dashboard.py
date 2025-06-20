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

# Step 1: Upload Credit Request Template
st.header("Step 1: Upload Credit Request Template")
uploaded_excel = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

if uploaded_excel:
    # Load Excel
    df_input = pd.read_excel(uploaded_excel)

    # Add missing columns expected by the app
    for col in ['Sales Rep', 'Status', 'Date', 'Ticket Number']:
        if col not in df_input.columns:
            df_input[col] = ""

    # Define final column schema
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

    # Clean and calculate
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

    # Step 3: Add Ticket Info
    st.header("Step 3: Add Ticket Info")
    with st.form("credit_form"):
        ticket_number = st.text_input("🎫 Ticket Number", value="")
        ticket_date = st.date_input("📅 Ticket Date", value=datetime.today())
        status_text = st.text_area("📝 Status Description", height=200)
        sales_rep_input = st.text_input("🧑‍💼 Sales Rep", value="")
        submitted = st.form_submit_button("Submit Record")

    if submitted:
        df_main_structure.at[0, 'Ticket Number'] = ticket_number
        df_main_structure.at[0, 'Date'] = pd.to_datetime(ticket_date).date()
        df_main_structure.at[0, 'Status'] = status_text
        df_main_structure.at[0, 'Sales Rep'] = sales_rep_input

        st.success("✅ Ticket Info Updated!")

        # Optionally show result
        st.dataframe(df_main_structure)

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


