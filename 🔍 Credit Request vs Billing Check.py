import streamlit as st
import pandas as pd

st.title("📄 Credit Request Matcher")

st.markdown("Upload the *Billing Master* and the *New Credit Form* files to find matching Invoice + Item pairs.")

# Step 1: Upload files
billing_file = st.file_uploader("🧾 Upload Billing Master Excel", type=["xlsx", "xlsm"])
credit_file = st.file_uploader("📝 Upload New Credit Form Excel", type=["xlsx", "xlsm"])

if billing_file and credit_file:
    # Step 2: Load both files
    df_billing = pd.read_excel(billing_file, engine="openpyxl")
    df_credit = pd.read_excel(credit_file, engine="openpyxl")

    # Step 3: Standardize column names
    df_billing.rename(columns={
        'Doc No': 'Invoice Number',
        'Item No.': 'Item Number'
    }, inplace=True)

    # Step 4: Drop NaNs where comparison can't happen
    df_credit_clean = df_credit.dropna(subset=['Invoice Number', 'Item Number']).copy()

    # Step 5: Convert both keys to strings
    df_credit_clean['Invoice Number'] = df_credit_clean['Invoice Number'].astype(str).str.strip()
    df_credit_clean['Item Number'] = df_credit_clean['Item Number'].astype(str).str.strip()
    df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
    df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()

    # Step 6: Create matching keys
    credit_keys = set(zip(df_credit_clean['Invoice Number'], df_credit_clean['Item Number']))
    billing_keys = set(zip(df_billing['Invoice Number'], df_billing['Item Number']))
    common_pairs = credit_keys & billing_keys

    # Step 7: Filter matches
    df_matches = df_credit_clean[
        df_credit_clean[['Invoice Number', 'Item Number']].apply(tuple, axis=1).isin(common_pairs)
    ]

    st.success(f"✅ Found {len(df_matches)} matching records.")

    # Step 8: Show and optionally export
    st.dataframe(df_matches)

    # Optional download
    csv = df_matches.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Matches as CSV", csv, "matched_records.csv", "text/csv")

else:
    st.info("⬆️ Please upload both files to begin.")
