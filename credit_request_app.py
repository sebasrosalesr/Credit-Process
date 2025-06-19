### Interface + SQL Database with Streamlit
import streamlit as st
import pandas as pd
import os
import sqlite3
from datetime import datetime

# === CONFIGURATION ===
st.set_page_config(page_title="Credit Request Uploader", layout="wide")
folder_path = "uploads"  # Folder to hold uploaded Excel files temporarily
os.makedirs(folder_path, exist_ok=True)

# === Upload Excel File ===
st.title("📥 Credit Request Uploader")
uploaded_file = st.file_uploader("Upload Credit Request Excel file", type=["xls", "xlsx", "xlsm"])

if uploaded_file is not None:
    file_name = uploaded_file.name
    file_path = os.path.join(folder_path, file_name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.read())

    df_input = pd.read_excel(file_path)

    # === STEP 1: Define DB schema ===
    columns = [
        'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
        'Extended Correct Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit', 'Status', 'Ticket Number', 'Sales Rep'
    ]
    required_cols = [
        'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price',
        'Corrected Unit Price', 'Credit Request Total', 'Requested By',
        'Reason for Credit'
    ]

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
    df_filtered['Sales Rep'] = ''

    df_main_structure = df_filtered[columns].copy()

    # === Manual Input ===
    with st.form("manual_form"):
        st.subheader("📝 Ticket Metadata")
        ticket_num = st.text_input("Ticket Number")
        ticket_date = st.date_input("Ticket Date")
        sales_rep = st.text_input("Sales Rep")
        status_input = st.text_area("Status Description")
        submitted = st.form_submit_button("Submit Entry")

        if submitted:
            df_main_structure.at[0, 'Ticket Number'] = ticket_num
            df_main_structure.at[0, 'Date'] = ticket_date
            df_main_structure.at[0, 'Status'] = status_input
            df_main_structure.at[0, 'Sales Rep'] = sales_rep

            st.success("Ticket data updated.")
            st.dataframe(df_main_structure.head(5))

            # === Save Backup ===
            backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            df_main_structure.to_excel(backup_path, index=False)
            st.download_button("📁 Download Backup Excel", data=open(backup_path, 'rb').read(), file_name=backup_path)

            # === Database Save ===
            db_path = "Credits_DB.db"
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
            ''', (file_name, len(new_rows), len(df_main_structure) - len(new_rows)))

            conn.commit()
            conn.close()

            st.success("✅ Upload to database complete!")
            st.write(f"🔄 Rows inserted: {len(new_rows)}")
            st.write(f"🚫 Duplicates skipped: {len(df_main_structure) - len(new_rows)}")
