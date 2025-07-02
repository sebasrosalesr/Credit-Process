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
db_path = "credits.db"
conn = sqlite3.connect(db_path)

# --- Streamlit UI ---
st.title("📄 Credit Request Dashboard")

# Step 1: Upload File
st.header("Step 1: Upload Credit Request Template")
uploaded_file = st.file_uploader("📂 Upload Excel Template", type=["xls", "xlsx", "xlsm"])

if uploaded_file:
    df = pd.read_excel(uploaded_file)

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

    # --- Clean numeric fields ---
    for field in ['QTY', 'Unit Price', 'Corrected Unit Price', 'Credit Request Total']:
        df_filtered[field] = df_filtered[field].astype(str).str.replace(r'[$,]', '', regex=True)
        df_filtered[field] = pd.to_numeric(df_filtered[field], errors='coerce')

    df_filtered.dropna(subset=['Invoice Number', 'Item Number'], inplace=True)
    df_filtered.fillna({field: 0 for field in ['QTY', 'Unit Price', 'Corrected Unit Price', 'Credit Request Total']}, inplace=True)

    # --- Fetch existing Firebase entries for deduplication ---
    try:
        existing_data = ref.get()
        existing_pairs = set()
        if existing_data:
            for rec in existing_data.values():
                existing_pairs.add((rec.get('Invoice Number'), str(rec.get('Item Number'))))
    except Exception as e:
        st.error(f"❌ Error reading from Firebase: {e}")
        existing_pairs = set()

    # Step 2: Form Input
    st.header("Step 2: Add Ticket Info")
    with st.form("ticket_entry"):
        ticket_number = st.text_input("🎫 Ticket Number")
        ticket_date = st.date_input("📅 Ticket Date", value=datetime.today())
        status = st.text_area("📜 Status / Reason")

        sales_rep_options = sorted([
            'HOUSE', 'SA/AR', 'nan', 'AR/KE', 'BPARKER', 'RFRIEDMAN', 'AROSENFELD', 'DR/TU',
            'JK/AR', 'AR/MG', 'CHRISWYLER', 'JGOULDING', 'AL/NL', 'MALCARAZ', 'TJUNIK',
            'ALANDAU', 'NYS', 'EB/MC/MF/SM', 'EB/MC/MF/SM/SP', 'ELIB', 'MF/SG', 'TRENNERT',
            'SA/MG', 'WNISCHT', 'AR/BG', 'RMAIRS', 'BWERCZBERGER', 'AL/AR/BG', 'EB', 'JEARL',
            'TWHITZEL', 'JSWEENEY', 'JMCSHANNOCK', 'DDFILIPPO', 'CTHOMAS', 'NELLMAN',
            'BMONCZYK', 'SADAMS', 'DW/EB/MC/MF/SM', 'DWEBMCMFSMSP', 'DW/EB/MF/MC/SP/',
            'JC/JT', 'RF/AR', 'RDORAN', 'SMARCIANO', 'JCROSGROVE', 'MC/MF', 'MC/SM',
            'BOBGOLD', 'ELI/BOB', 'MFINE', 'CFAULKNER', 'NLANDAU', 'MF', 'ALLMED',
            'CW/SM', 'SUB02', 'AOBEZIL', 'EB/MC/MF', 'JTIPTON', 'AR/JS', 'DW/MF',
            'BRANDALL', 'KM/RM', 'MDESIMONE', 'MEYER', 'MC', 'CHI/NL', 'BBINDEL',
            'MWEENIG', 'NMERRITT', 'DW', 'SDECKERT', 'MC/MF/SM', 'ELIB/MC/MF/SIMI',
            'DW/MF/SM', 'EB/SG', 'EB/MC/MF/SG/SM', 'NBITTERMAN', 'SM/MC/EB/MF/AL',
            'MLANDAU', 'EB/MF/MC/SP/SM', 'JMILLER', 'ELIB/MC', 'JGOLESTANI', 'MF/SM',
            'JSOLOMON', 'AL/NL/TJ', 'MVZ', 'SIMI', 'CWILLIAMS', 'DW/EB/MC/MF/SIM',
            'TPETERS', 'BP/NL', 'DW/SIMI/MF', 'JDUCKWORTH', 'EB/MC', 'DWEINBERGER',
            'AL/MF', 'SIMI/MF', 'DD/AS', 'MAMCGOWEN', 'AROEBUCK', 'JM/BB', 'JGRANT',
            'ALEBMCMFSMSP', 'AROTH', 'SIMI/MC/MF', 'JSHALLMAN', 'DROPA', 'ASPEAR',
            'JS/DW', 'JE/JT', 'AL/AR', 'SIMI/MC', 'ELIB/SIMI', 'JM/MA', 'RA/KE',
            'MC/MF/SG', 'JC/JE', 'EB/SM', 'MDELGADO', 'BW/CW', 'ELI/SHAWEL',
            'BROOSEVELT', 'DYONA', 'MVANZELST', 'ROB', 'ELI/BOB/MF', 'MC/MF/SG/SM',
            'AL/MC', 'SIMI/MC/ELIB', 'TJ/NB', 'MC/SG', 'MF/SP/RF', 'AL/JG', 'MEDSPARK',
            'JM/AS', 'CRAMIREZ', 'CF/AR', 'SM', 'TJ/NL', 'AO/MA', 'MCHASE',
            'KSCHWIETERMAN', 'ELI BERKOVICH', 'CW/TJ', 'MW/TJ', 'KEMORY', 'RA', 'BG',
            'PECK', 'EB/NB/C/F/M/P', 'CROBINSON', 'MF/NL', 'SG', 'SD/SM',
            'EBMCMFSMSPBW', 'BB/MDS', 'BFR', 'TJ/SA', 'NB/JE', 'BOB/MF/SIMI/MC',
            'DW/MC/MF/SM', 'CLANDAU/CWYLER', 'ELIB/MC/MF/RG/S'
        ])
        sales_rep = st.selectbox("👤 Sales Rep", options=sales_rep_options)

        submitted = st.form_submit_button("Submit Record")

        if submitted:
            count = 0
            for _, row in df_filtered.iterrows():
                inv = str(row['Invoice Number'])
                item = str(row['Item Number'])

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
