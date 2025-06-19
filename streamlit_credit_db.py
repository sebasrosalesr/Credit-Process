import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
import base64

st.title("📋 Credit Request Entry Tool")
st.markdown("---")

# === Upload database file ===
st.header("Step 1: Upload Database")
uploaded_db = st.file_uploader("Upload your SQLite .db file", type=["db"])

if uploaded_db:
    db_path = uploaded_db.name
    with open(db_path, "wb") as f:
        f.write(uploaded_db.getbuffer())

    # === Upload Excel Template ===
    st.header("Step 2: Upload Credit Request Template")
    uploaded_excel = st.file_uploader("Upload Excel file", type=["xlsx", "xlsm"])

    if uploaded_excel:
        df_input = pd.read_excel(uploaded_excel)

        # Clean expected columns
        expected_cols = [
            'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
            'Item Number', 'QTY', 'Unit Price', 'Extended Price',
            'Corrected Unit Price', 'Credit Request Total', 'Requested By',
            'Reason for Credit'
        ]

        for col in expected_cols:
            if col not in df_input.columns:
                df_input[col] = None

        df_input = df_input[expected_cols].copy()

        # Convert types and calculate derived field
        df_input['QTY'] = pd.to_numeric(df_input['QTY'], errors='coerce')
        df_input['Unit Price'] = pd.to_numeric(df_input['Unit Price'], errors='coerce')
        df_input['Corrected Unit Price'] = pd.to_numeric(df_input['Corrected Unit Price'], errors='coerce')

        df_input['Extended Correct Price'] = (
            df_input['Unit Price'] * df_input['QTY'] - df_input['Corrected Unit Price'] * df_input['QTY']
        )

        # Add additional columns
        df_input['Date'] = pd.NaT
        df_input['Status'] = ''
        df_input['Ticket Number'] = ''
        df_input['Sales Rep'] = ''

        # === Manual Entry Form ===
        st.header("Step 3: Fill Ticket Info")
        with st.form("ticket_form"):
            ticket_num = st.text_input("Ticket Number")
            ticket_date = st.date_input("Ticket Date", value=datetime.today())
            status_input = st.text_area("Status Description")
            sales_rep = st.text_input("Sales Rep")
            submitted = st.form_submit_button("✅ Submit Entry")

        if submitted:
            df_input.at[0, 'Ticket Number'] = ticket_num
            df_input.at[0, 'Date'] = ticket_date
            df_input.at[0, 'Status'] = status_input
            df_input.at[0, 'Sales Rep'] = sales_rep

            # Connect to SQLite and insert
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credits (
                    Date TEXT,
                    "Credit Type" TEXT,
                    "Issue Type" TEXT,
                    "Customer Number" TEXT,
                    "Invoice Number" TEXT,
                    "Item Number" TEXT,
                    QTY REAL,
                    "Unit Price" REAL,
                    "Extended Price" REAL,
                    "Corrected Unit Price" REAL,
                    "Extended Correct Price" REAL,
                    "Credit Request Total" REAL,
                    "Requested By" TEXT,
                    "Reason for Credit" TEXT,
                    "Status" TEXT,
                    "Ticket Number" TEXT,
                    "Sales Rep" TEXT
                )
            ''')

            # Deduplication
            existing = pd.read_sql_query("SELECT `Invoice Number`, `Item Number` FROM credits", conn)
            existing_pairs = set(zip(existing['Invoice Number'], existing['Item Number']))

            new_rows = df_input[~df_input.apply(
                lambda r: (r['Invoice Number'], r['Item Number']) in existing_pairs, axis=1)]

            if not new_rows.empty:
                new_rows.to_sql('credits', conn, if_exists='append', index=False)

            conn.commit()
            conn.close()

            st.success("✅ Entry successfully submitted!")

            # === Download Updated DB ===
            with open(db_path, 'rb') as f:
                db_bytes = f.read()

            b64 = base64.b64encode(db_bytes).decode()
            href = f'<a href="data:application/octet-stream;base64,{b64}" download="Credits_DB.db">📥 Download Updated DB</a>'
            st.markdown(href, unsafe_allow_html=True)
