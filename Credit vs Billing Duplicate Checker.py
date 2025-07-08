import streamlit as st
import pandas as pd

st.set_page_config(page_title="Credit vs Billing Duplicate Checker", layout="wide")

st.title("🔍 Credit Request & Billing Master - Duplicate Finder")

# --- Upload Credit Request Template ---
st.header("Step 1: Upload Credit Request Template (Exported from Firebase)")
credit_file = st.file_uploader("📤 Upload Credit Request Excel", type=["xlsx", "xls"])

if credit_file:
    df_credit = pd.read_excel(credit_file)

    expected_cols = ['Invoice Number', 'Item Number', 'Date']
    missing_cols = [col for col in expected_cols if col not in df_credit.columns]

    if missing_cols:
        st.error(f"❌ Missing column(s): {', '.join(missing_cols)}")
        st.stop()

    df_credit = df_credit.dropna(subset=['Invoice Number', 'Item Number', 'Date']).copy()
    df_credit['Invoice Number'] = df_credit['Invoice Number'].astype(str).str.strip()
    df_credit['Item Number'] = df_credit['Item Number'].astype(str).str.strip()

    # --- Upload Billing Master ---
    st.header("Step 2: Upload Billing Master File")
    billing_file = st.file_uploader("📤 Upload Billing Master Excel", type=["xlsx", "xls"])

    if billing_file:
        df_billing = pd.read_excel(billing_file)

        # Try flexible renaming in case headers vary slightly
        billing_col_map = {
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number',
            'Item No': 'Item Number',
            'Doc NoItem No#': None  # will handle separately if needed
        }
        df_billing.rename(columns={k: v for k, v in billing_col_map.items() if k in df_billing.columns}, inplace=True)

        # If combined column exists, split it
        if 'Doc NoItem No#' in df_billing.columns:
            df_billing[['Invoice Number', 'Item Number']] = df_billing['Doc NoItem No#'].astype(str).str.extract(r'(INV\d+)(\d+)')
        
        if 'Invoice Number' not in df_billing.columns or 'Item Number' not in df_billing.columns:
            st.error("❌ Could not detect 'Invoice Number' and 'Item Number' columns in the Billing Master.")
            st.stop()

        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
        df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()

        # --- Find Matching Invoice+Item Pairs ---
        firebase_keys = set(zip(df_credit['Invoice Number'], df_credit['Item Number']))
        billing_keys = set(zip(df_billing['Invoice Number'], df_billing['Item Number']))
        common_pairs = firebase_keys & billing_keys

        # Filter credit requests for those duplicates
        df_matches = df_credit[df_credit[['Invoice Number', 'Item Number']].apply(tuple, axis=1).isin(common_pairs)]

        st.success(f"✅ Found {len(df_matches)} matching records between credit requests and billing master.")
        st.dataframe(df_matches)

        # Optional export
        csv = df_matches.to_csv(index=False).encode('utf-8')
        st.download_button("⬇️ Download Matching Records CSV", csv, "matching_records.csv", "text/csv")
