from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# --- Firebase Init ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })
ref = db.reference('credit_requests')

# --- Output Columns ---
standard_columns = [
    'Date', 'Credit Type', 'Issue Type', 'Customer Number', 'Invoice Number',
    'Item Number', 'QTY', 'Unit Price', 'Extended Price', 'Corrected Unit Price',
    'Extended Correct Price', 'Credit Request Total', 'Requested By',
    'Reason for Credit', 'Status', 'Ticket Number'
]

# --- Mapping Definitions ---
macro_mapping = {
    'Date': 'Req Date', 'Credit Type': 'CRType', 'Issue Type': 'Type',
    'Customer Number': 'Cust ID', 'Invoice Number': 'Doc No', 'Item Number': 'Item No.',
    'Credit Request Total': 'Total Credit Amt', 'Requested By': 'Requested By',
    'Reason for Credit': 'Reason', 'Status': 'Status', 'Ticket Number': None
}

pump_mapping = {
    'Date': 'DOCDATE', 'Customer Number': 'CUSTNMBR', 'Invoice Number': 'SOPNUMBE',
    'Item Number': 'ITEMNMBR', 'QTY': 'QUANTITY', 'Unit Price': 'UNITPRCE',
    'Extended Price': 'XTNDPRCE'
}

# --- Convert Function ---
def convert_file(df, mapping):
    df_out = pd.DataFrame(columns=standard_columns)
    for out_col in standard_columns:
        source_col = mapping.get(out_col)
        if source_col and source_col in df.columns:
            df_out[out_col] = df[source_col]
        else:
            df_out[out_col] = None
    return df_out

# --- Streamlit App ---
st.set_page_config(page_title="🧾 Credit File + Status Checker", layout="wide")
st.title("🧾 Drop Credit Requests & View Current Status")
st.markdown("Upload Macro or Pump Order files. The app will find and display the status for each request.")

uploaded_files = st.file_uploader("📥 Upload Excel files", type=['xlsx', 'xlsm', 'xls'], accept_multiple_files=True)

converted_frames = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        df = pd.read_excel(uploaded_file)
        cols = set(df.columns)

        if 'Req Date' in cols and 'Cust ID' in cols:
            st.info(f"📎 Detected: Macro Format — {uploaded_file.name}")
            converted = convert_file(df, macro_mapping)
        elif 'CUSTNMBR' in cols and 'ITEMNMBR' in cols:
            st.info(f"🔧 Detected: Pump Format — {uploaded_file.name}")
            df = df[df['UNITPRCE'] != 0]
            converted = convert_file(df, pump_mapping)
        else:
            st.warning(f"⚠️ Skipped {uploaded_file.name} — Format not recognized.")
            continue

        converted['Source File'] = uploaded_file.name
        converted_frames.append(converted)

# === Lookup in Firebase ===
if converted_frames:
    st.divider()
    st.subheader("🔍 Checking Status in Firebase")

    combined_df = pd.concat(converted_frames, ignore_index=True)
    lookup_pairs = set(zip(combined_df['Invoice Number'].astype(str).str.strip(),
                           combined_df['Item Number'].astype(str).str.strip()))

    firebase_data = ref.get()
    firebase_matches = []

    if firebase_data:
        for key, record in firebase_data.items():
            inv = str(record.get("Invoice Number", "")).strip()
            item = str(record.get("Item Number", "")).strip()
            if (inv, item) in lookup_pairs:
                record["Record ID"] = key
                record["Match Invoice"] = inv
                record["Match Item"] = item
                firebase_matches.append(record)

    if firebase_matches:
        df_firebase = pd.DataFrame(firebase_matches)
        st.success(f"✅ Found {len(df_firebase)} matching records in Firebase")
        st.dataframe(df_firebase)

        # Download
        csv_buf = io.StringIO()
        df_firebase.to_csv(csv_buf, index=False)
        st.download_button("⬇️ Download Matching Results", data=csv_buf.getvalue(),
                           file_name="firebase_status_lookup.csv", mime="text/csv")
    else:
        st.warning("❌ No matches found in Firebase for uploaded invoice/item pairs.")
