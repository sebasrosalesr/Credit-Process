import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import io

# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Load DOC Analysis File with Header Detection ---
def load_doc_analysis_file(file):
    raw_df = pd.read_excel(file, header=None)

    # Scan first 10 rows for header
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

# --- Streamlit UI ---
st.set_page_config(page_title="DOC Analysis Lookup", layout="wide")
st.title("📄 DOC Analysis File Lookup")
st.markdown("Upload a DOC Analysis file (Excel format). The system will auto-detect headers and check for matches in the database.")

# --- Upload and Process ---
uploaded_file = st.file_uploader("📥 Upload DOC Analysis Excel file", type=["xlsx", "xls", "xlsm"])

if uploaded_file:
    try:
        df_doc = load_doc_analysis_file(uploaded_file)
        st.success(f"✅ Loaded file with {df_doc.shape[0]} rows")

        # Normalize and extract key columns
        df_doc['SOPNUMBE'] = df_doc['SOPNUMBE'].astype(str).str.strip()
        df_doc['ITEMNMBR'] = df_doc['ITEMNMBR'].astype(str).str.strip()
        lookup_pairs = set(zip(df_doc['SOPNUMBE'], df_doc['ITEMNMBR']))

        # Load Firebase
        firebase_data = ref.get()
        matches = []

        if firebase_data:
            for key, record in firebase_data.items():
                inv = str(record.get("Invoice Number", "")).strip()
                item = str(record.get("Item Number", "")).strip()
                if (inv, item) in lookup_pairs:
                    record["Record ID"] = key
                    record["Match Invoice"] = inv
                    record["Match Item"] = item
                    matches.append(record)

        if matches:
            st.success(f"🔎 Found {len(matches)} matching records in Firebase")
            df_results = pd.DataFrame(matches)
            st.dataframe(df_results)

            # Download option
            csv_buf = io.StringIO()
            df_results.to_csv(csv_buf, index=False)
            st.download_button("⬇️ Download Results", data=csv_buf.getvalue(),
                               file_name="matched_doc_analysis.csv", mime="text/csv")
        else:
            st.warning("❌ No matches found for uploaded pairs.")

    except Exception as e:
        st.error(f"🚨 Error: {e}")
