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
        df_credit = pd.read_excel(credit_file, engine="openpyxl")
        df_billing = pd.read_excel(billing_file, engine="openpyxl")

        # Rename billing columns for matching
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number'
        }, inplace=True)

        # Drop NaNs from Credit Form where matching isn't possible
        df_credit_clean = df_credit.dropna(subset=['Invoice Number', 'Item Number']).copy()

        # Convert keys to strings and strip
        df_credit_clean['Invoice Number'] = df_credit_clean['Invoice Number'].astype(str).str.strip()
        df_credit_clean['Item Number'] = df_credit_clean['Item Number'].astype(str).str.strip()
        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
        df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()

        # Create key pairs
        credit_keys = set(zip(df_credit_clean['Invoice Number'], df_credit_clean['Item Number']))
        billing_keys = set(zip(df_billing['Invoice Number'], df_billing['Item Number']))
        common_pairs = credit_keys & billing_keys

        # Filter matches
        df_matches = df_credit_clean[
            df_credit_clean[['Invoice Number', 'Item Number']].apply(tuple, axis=1).isin(common_pairs)
        ]

        st.success(f"✅ Found {len(df_matches)} matching records.")
        st.dataframe(df_matches)

        # Downloadable CSV
        csv = df_matches.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Matches as CSV", csv, "matched_records.csv", "text/csv")

    except Exception as e:
        st.error(f"❌ Error processing files: {e}")

else:
    st.info("⬆️ Please upload both files to begin.")
