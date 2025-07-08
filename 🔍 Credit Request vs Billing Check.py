import streamlit as st
import pandas as pd

st.title("🔍 Credit Request vs Billing Check")

# --- Upload both files ---
st.header("Step 1: Upload Files")
req_file = st.file_uploader("📂 Upload Credit Request Template", type=["xlsx", "xlsm", "xls"])
bill_file = st.file_uploader("📂 Upload Billing Master Excel", type=["xlsx", "xlsm", "xls"], key="bill")

if req_file and bill_file:
    try:
        df_req = pd.read_excel(req_file)
        df_bill = pd.read_excel(bill_file)

        # --- Rename billing columns ---
        df_bill.rename(columns={'Doc No': 'Invoice Number', 'Item No.': 'Item Number'}, inplace=True)

        # --- Clean & filter requestor data ---
        df_req = df_req.dropna(subset=['Invoice Number', 'Item Number', 'Date']).copy()
        df_req['Invoice Number'] = df_req['Invoice Number'].astype(str).str.strip()
        df_req['Item Number'] = df_req['Item Number'].astype(str).str.strip()
        df_bill['Invoice Number'] = df_bill['Invoice Number'].astype(str).str.strip()
        df_bill['Item Number'] = df_bill['Item Number'].astype(str).str.strip()

        # --- Build match sets ---
        keys_req = set(zip(df_req['Invoice Number'], df_req['Item Number']))
        keys_bill = set(zip(df_bill['Invoice Number'], df_bill['Item Number']))
        common_keys = keys_req & keys_bill

        # --- Find matching rows ---
        df_matches = df_req[
            df_req[['Invoice Number', 'Item Number']].apply(tuple, axis=1).isin(common_keys)
        ]

        st.success(f"✅ Found {len(df_matches)} matched record(s) in billing.")
        st.dataframe(df_matches)

    except Exception as e:
        st.error(f"❌ Error processing files: {e}")
