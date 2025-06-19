import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime

# --- Configuration ---
REQUIRED_COLUMNS = [
    'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price',
    'Corrected Unit Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit'
]

FINAL_COLUMNS = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit', 'Status', 'Ticket Number', 'Sales Rep'
]

st.title("📥 Credit Request Uploader")

# --- Upload Section ---
db_file = st.file_uploader("Upload SQLite DB File", type=["db"])
excel_file = st.file_uploader("Upload Credit Request Excel Template", type=["xlsx", "xls", "xlsm"])

if db_file and excel_file:
    try:
        # Save uploaded DB locally
        db_path = "/tmp/uploaded_db.db"
        with open(db_path, "wb") as f:
            f.write(db_file.read())

        # Read Excel
        df_input = pd.read_excel(excel_file)

        # Show uploaded columns
        st.subheader("Uploaded Excel Columns")
        st.write(df_input.columns.tolist())

        # Check for missing columns
        missing_cols = [col for col in REQUIRED_COLUMNS if col not in df_input.columns]
        if missing_cols:
            st.error(f"❌ Missing required columns: {missing_cols}")
            st.stop()

        # Process the data
        df_filtered = df_input[REQUIRED_COLUMNS].copy()
        df_filtered['QTY'] = pd.to_numeric(df_filtered['QTY'], errors='coerce')
        df_filtered['Unit Price'] = pd.to_numeric(df_filtered['Unit Price'], errors='coerce')
        df_filtered['Corrected Unit Price'] = pd.to_numeric(df_filtered['Corrected Unit Price'], errors='coerce')
        df_filtered['Extended Correct Price'] = (
            df_filtered['Unit Price'] * df_filtered['QTY'] -
            df_filtered['Corrected Unit Price'] * df_filtered['QTY']
        )

        # Manual inputs
        ticket_number = st.text_input("Ticket Number")
        ticket_date = st.date_input("Ticket Date")
        status = st.text_area("Status Description")
        sales_rep = st.text_input("Sales Rep")

        if st.button("✅ Submit Entry"):
            df_filtered['Date'] = ticket_date
            df_filtered['Ticket Number'] = ticket_number
            df_filtered['Status'] = status
            df_filtered['Sales Rep'] = sales_rep

            df_final = df_filtered[FINAL_COLUMNS].copy()

            # Connect to DB
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Ensure tables exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS credits (
                    Date TEXT, "Credit Type" TEXT, "Issue Type" TEXT, "Customer Number" TEXT,
                    "Invoice Number" TEXT, "Item Number" TEXT, QTY REAL, "Unit Price" REAL,
                    "Extended Price" REAL, "Corrected Unit Price" REAL, "Extended Correct Price" REAL,
                    "Credit Request Total" REAL, "Requested By" TEXT, "Reason for Credit" TEXT,
                    "Status" TEXT, "Ticket Number" TEXT, "Sales Rep" TEXT
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

            # Deduplicate
            existing = pd.read_sql_query("SELECT `Invoice Number`, `Item Number` FROM credits", conn)
            existing_pairs = set(zip(existing['Invoice Number'], existing['Item Number']))

            new_rows = df_final[~df_final.apply(
                lambda r: (r['Invoice Number'], r['Item Number']) in existing_pairs, axis=1
            )]

            if not new_rows.empty:
                new_rows.to_sql('credits', conn, if_exists='append', index=False)

            cursor.execute('''
                INSERT INTO upload_log (filename, rows_inserted, duplicates_skipped)
                VALUES (?, ?, ?)
            ''', (excel_file.name, len(new_rows), len(df_final) - len(new_rows)))

            conn.commit()
            conn.close()

            st.success(f"✅ {len(new_rows)} new rows uploaded. {len(df_final) - len(new_rows)} duplicates skipped.")

            st.download_button("⬇️ Download Backup Excel", data=df_final.to_csv(index=False), file_name="uploaded_backup.csv")

    except Exception as e:
        st.error(f"❌ An error occurred: {e}")

else:
    st.info("Please upload both an Excel template and a database file to proceed.")
