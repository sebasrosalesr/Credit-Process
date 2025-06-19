import pandas as pd
import os
import sqlite3
from datetime import datetime
from IPython.display import display
import streamlit as st

# === STREAMLIT CONFIGURATION ===
st.set_page_config(page_title="Credit Request Uploader", layout="wide")
st.title("📄 Credit Request Uploader")

# === FILE UPLOAD ===
db_file = st.file_uploader("Upload your SQLite DB file (Credits_DB.db):", type=["db"])
template_file = st.file_uploader("Upload Credit Request Excel file:", type=["xls", "xlsx", "xlsm"])

if db_file and template_file:
    # === SETUP ===
    db_path = "/tmp/uploaded_Credits_DB.db"
    with open(db_path, "wb") as f:
        f.write(db_file.read())

    df_input = pd.read_excel(template_file)

    # === SCHEMA ===
    columns = [
        'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
        'Extended Correct Price', 'Credit Request Total', 'Requested By', 'Sales Rep',
        'Reason for Credit', 'Status', 'Ticket Number'
    ]

    required_cols = [
        'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
        'Item Number', 'QTY', 'Unit Price', 'Extended Price',
        'Corrected Unit Price', 'Credit Request Total', 'Requested By',
        'Sales Rep', 'Reason for Credit'
    ]

    # === DATA CLEANING ===
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

    # === USER INPUT ===
    st.subheader("📌 Ticket Info")
    ticket_num = st.text_input("Ticket Number", value="R-")
    ticket_date = st.date_input("Date", value=datetime.today())
    status_input = st.text_area("📝 Status Description")

    if st.button("Submit to Database"):
        df_main_structure.at[0, 'Ticket Number'] = ticket_num
        df_main_structure.at[0, 'Date'] = ticket_date
        df_main_structure.at[0, 'Status'] = status_input

        filename = "MANUAL_ENTRY_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
        df_main_structure.to_excel(f"/tmp/{filename}", index=False)

        # === DB CONNECTION ===
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
            "Sales Rep" TEXT,
            "Reason for Credit" TEXT,
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

        st.success(f"✅ Uploaded {len(new_rows)} new rows. {len(df_main_structure) - len(new_rows)} duplicates skipped.")
        st.info(f"📁 Backup saved as: {filename}")