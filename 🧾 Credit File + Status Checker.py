from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io
import re

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

doc_analysis_mapping = {
    'Invoice Number': 'SOP Number',
    'Item Number': 'Item Number'
}

# --- DOC Header Detection (Flexible) ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)
    header_row = None
    for i in range(10):
        row = raw_df.iloc[i].astype(str).str.upper().str.strip()
        if "SOP NUMBER" in row.values and "ITEM NUMBER" in row.values:
            header_row = i
            break
    if header_row is None:
        raise ValueError("❌ Could not detect header row. Please ensure 'SOP Number' and 'Item Number' are present.")
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

# --- Update Extractor ---
def extract_update(status_text):
    if pd.isna(status_text):
        return "No updates"
    match = re.search(r'Update:\s*(.*)', status_text)
    return match.group(1).strip() if match else "No updates"

# --- Streamlit UI ---
st.set_page_config(page_title="📎 Credit File Pair Lookup", layout="wide")
st.title("📎 Credit Request File Lookup by Invoice + Item")
st.markdown("Upload a **Macro** or **DOC Analysis** file to check which (Invoice, Item) pairs already exist in Firebase.")

uploaded_file = st.file_uploader("📤 Upload File", type=["xlsx", "xls", "xlsm"])

if uploaded_file:
    try:
        df_raw = pd.read_excel(uploaded_file, nrows=5)
        cols = set(df_raw.columns)

        # Detect Macro File
        if "Doc No" in cols and "Item No." in cols:
            st.info("📘 Format Detected: Macro File")
            df = pd.read_excel(uploaded_file)
            search_df = convert_to_invoice_item_df(df, macro_mapping)

        # Detect DOC Analysis File by scanning for headers
        else:
            st.info("📄 Trying to detect DOC Analysis headers...")
            df = load_doc_analysis_file(uploaded_file)
            if "SOP Number" in df.columns and "Item Number" in df.columns:
                st.success("📄 Format Detected: DOC Analysis File")
                search_df = convert_to_invoice_item_df(df, doc_analysis_mapping)
            else:
                st.warning("⚠️ Could not find required columns in the detected DOC Analysis file.")
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

            # ✅ Clean and transform
            df_results.drop(columns=["Sales Rep", "RTN_CR_No", "Reason for Credit"], errors="ignore", inplace=True)
            df_results["Latest Update"] = df_results["Status"].apply(extract_update)

            st.success(f"✅ Found {len(df_results)} matching records in Firebase")

            # --- Display cleaned table ---
            st.dataframe(df_results[['Match Invoice', 'Match Item', 'Date', 'Latest Update', 'Credit Request Total']])

            # --- Download option ---
            csv_buf = io.StringIO()
            df_results[['Match Invoice', 'Match Item', 'Latest Update']].to_csv(csv_buf, index=False)
            st.download_button("⬇️ Download Results", data=csv_buf.getvalue(),
                               file_name="firebase_matches_with_updates.csv", mime="text/csv")
        else:
            st.warning("❌ No matching records found in Firebase.")

    except Exception as e:
        st.error(f"🚨 Error processing file: {e}")
