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

# --- Mapping Definitions ---
macro_mapping = {
    'Invoice Number': 'Doc No',
    'Item Number': 'Item No.'
}

pump_mapping = {
    'Invoice Number': 'SOPNUMBE',
    'Item Number': 'ITEMNMBR'
}

# --- DOC Header Detection ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if "SOPNUMBE" in row.values and "ITEMNMBR" in row.values:
            header_row = i
            break
    if header_row is None:
        raise ValueError("❌ Could not detect header row. Please check the file.")
    df = pd.read_excel(file, header=header_row)
    return df

# --- File Conversion Function ---
def convert_to_invoice_item_df(df, mapping):
    out_df = pd.DataFrame()
    for col in ['Invoice Number', 'Item Number']:
        source = mapping[col]
        if source in df.columns:
            out_df[col] = df[source].astype(str).str.strip()
        else:
            out_df[col] = None
    return out_df.dropna()

# --- Streamlit UI ---
st.set_page_config(page_title="📎 Credit File Pair Lookup", layout="wide")
st.title("📎 Credit Request File Lookup by Invoice + Item")
st.markdown("Upload a **Macro** or **DOC Analysis** file to check which (Invoice, Item) pairs already exist in Firebase.")

uploaded_file = st.file_uploader("📤 Upload File", type=["xlsx", "xls", "xlsm"])

if uploaded_file:
    try:
        df_raw = pd.read_excel(uploaded_file, nrows=5)
        cols = set(df_raw.columns)

        if "Doc No" in cols and "Item No." in cols:
            st.info("📘 Format Detected: Macro File")
            df = pd.read_excel(uploaded_file)
            search_df = convert_to_invoice_item_df(df, macro_mapping)

        elif any("SOPNUMBE" in str(cell) for cell in df_raw.iloc[0].values):
            st.info("📄 Format Detected: DOC Analysis File")
            df = load_doc_analysis_file(uploaded_file)
            search_df = convert_to_invoice_item_df(df, pump_mapping)

        else:
            st.warning("⚠️ File format not recognized.")
            st.stop()

        st.write(f"🔍 Found {len(search_df)} invoice/item pairs to check")

        # Firebase lookup
        firebase_data = ref.get()
        matches = []

        if firebase_data:
            lookup_pairs = set(zip(search_df['Invoice Number'], search_df['Item Number']))

            for key, record in firebase_data.items():
                inv = str(record.get("Invoice Number", "")).strip()
                item = str(record.get("Item Number", "")).strip()
                if (inv, item) in lookup_pairs:
                    record["Record ID"] = key
                    record["Match Invoice"] = inv
                    record["Match Item"] = item
                    matches.append(record)

        if matches:
            df_results = pd.DataFrame(matches)
            st.success(f"✅ Found {len(df_results)} matching records in Firebase")
            st.dataframe(df_results)

            # Download option
            csv_buf = io.StringIO()
            df_results.to_csv(csv_buf, index=False)
            st.download_button("⬇️ Download Results", data=csv_buf.getvalue(),
                               file_name="firebase_matches.csv", mime="text/csv")
        else:
            st.warning("❌ No matching records found in Firebase.")

    except Exception as e:
        st.error(f"🚨 Error processing file: {e}")
