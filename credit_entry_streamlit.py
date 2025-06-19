import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import os
import tempfile

# === CONFIG ===
st.set_page_config(page_title="Credit Request Entry", layout="wide")

# --- Title ---
st.title("📋 Credit Request Entry Interface")

# --- Upload Excel Template ---
st.header("Step 1: Upload Credit Request Template")
uploaded_excel = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

# --- Upload DB File ---
st.header("Step 2: Upload SQLite Database File")
uploaded_db = st.file_uploader("📂 Upload SQLite Database", type=["db"])

if uploaded_excel and uploaded_db:
    # Save DB temporarily
    db_path = os.path.join(tempfile.gettempdir(), uploaded_db.name)
    with open(db_path, "wb") as f:
        f.write(uploaded_db.read())

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
        ticket_date = st.date_input("📅 Ticket Date", value=datetime.today())
        status_text = st.text_area("📝 Status Description", height=200)
        submitted = st.form_submit_button("Submit Record")

    if submitted:
        df_main_structure.at[0, 'Ticket Number'] = ticket_number
        df_main_structure.at[0, 'Date'] = pd.to_datetime(ticket_date).date()
        df_main_structure.at[0, 'Status'] = status_text

        # Save backup
        filename = "MANUAL_ENTRY_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
        backup_path = os.path.join(tempfile.gettempdir(), filename)
        df_main_structure.to_excel(backup_path, index=False)

        # Upload to DB
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
            "Sales Rep" TEXT,
            "Status" TEXT,
            "Ticket Number" TEXT
        )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS upload_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rows_inserted INTEGER,
            duplicates_skipped INTEGER
        )
        ''')

        existing = pd.read_sql_query("SELECT `Invoice Number`, `Item Number` FROM credits", conn)
        existing_pairs = set(zip(existing['Invoice Number'], existing['Item Number']))
        new_rows = df_main_structure[~df_main_structure.apply(
            lambda r: (r['Invoice Number'], r['Item Number']) in existing_pairs, axis=1
        )]

        if not new_rows.empty:
            new_rows.to_sql('credits', conn, if_exists='append', index=False)

        cursor.execute('''
            INSERT INTO upload_log (filename, rows_inserted, duplicates_skipped)
            VALUES (?, ?, ?)
        ''', (filename, len(new_rows), len(df_main_structure) - len(new_rows)))

        conn.commit()
        conn.close()

        st.success("✅ Record inserted successfully!")
        st.info(f"🔄 Rows inserted: {len(new_rows)}")
        st.info(f"🚫 Duplicates skipped: {len(df_main_structure) - len(new_rows)}")

        with open(backup_path, 'rb') as f:
            st.download_button("📥 Download Backup Excel", data=f.read(), file_name=filename)

else:
    st.warning("📎 Please upload both the Excel file and the SQLite database to continue.")
