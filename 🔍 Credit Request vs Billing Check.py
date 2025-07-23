import streamlit as st
import pandas as pd

st.set_page_config(page_title="Credit Request vs Billing Check", layout="wide")

st.title("🔍 Credit Request vs Billing Check")
st.header("Step 1: Upload Files")

# Upload Credit Form
st.subheader("📤 Upload Credit Request Template")
credit_file = st.file_uploader("Drag and drop the Credit Form Excel here", type=["xlsx", "xlsm", "xls"])

# Upload Billing Master
st.subheader("📥 Upload Billing Master Excel")
billing_file = st.file_uploader("Drag and drop the Billing Master Excel here", type=["xlsx", "xlsm", "xls"])

# Process if both files are uploaded
if credit_file and billing_file:
    try:
        # Load files
        df_credit_raw = pd.read_excel(credit_file, engine="openpyxl")
        df_billing = pd.read_excel(billing_file, engine="openpyxl")

        # --- Step 1: Normalize column names in credit file ---
        credit_col_map = {
            'Item No.': 'Item Number',
            'Doc No': 'Invoice Number'
        }
        df_credit = df_credit_raw.rename(columns=credit_col_map)

        # Check if required columns now exist
        if not {'Invoice Number', 'Item Number'}.issubset(df_credit.columns):
            raise ValueError("❌ 'Invoice Number' and 'Item Number' not found in Credit Template (even after remapping).")

        # Normalize billing columns
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number'
        }, inplace=True)

        # Clean up
        df_credit_clean = df_credit.dropna(subset=['Invoice Number', 'Item Number']).copy()

        # Convert to strings and strip
        for df_ in [df_credit_clean, df_billing]:
            df_['Invoice Number'] = df_['Invoice Number'].astype(str).str.strip()
            df_['Item Number'] = df_['Item Number'].astype(str).str.strip()

        # Create matching keys
        credit_keys = set(zip(df_credit_clean['Invoice Number'], df_credit_clean['Item Number']))
        billing_keys = set(zip(df_billing['Invoice Number'], df_billing['Item Number']))
        common_pairs = credit_keys & billing_keys

        # Filter matched records
        df_matches = df_credit_clean[
            df_credit_clean[['Invoice Number', 'Item Number']].apply(tuple, axis=1).isin(common_pairs)
        ]

        st.success(f"✅ Found {len(df_matches)} matching records.")
        st.dataframe(df_matches)

        # Export to CSV
        csv = df_matches.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Matches as CSV", csv, "matched_records.csv", "text/csv")

    except Exception as e:
        st.error(f"❌ Error processing files: {e}")

else:
    st.info("⬆️ Please upload both files to begin.")
