import streamlit as st
import pandas as pd
from firebase_admin import credentials, db
import firebase_admin
from datetime import datetime

# --- Firebase Initialization ---
firebase_config = dict(st.secrets["firebase"])
firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# --- Streamlit UI ---
st.title("🔄 RTN/CR No. Updater")
st.write("Upload the Billing Master Excel to update missing RTN/CR Numbers in the Firebase database.")

# Upload Billing Master
billing_file = st.file_uploader("📥 Upload Billing Master Excel", type=["xlsx", "xlsm", "xls"])

if billing_file:
    try:
        df_billing = pd.read_excel(billing_file, engine="openpyxl")

        # Standardize key columns
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number'
        }, inplace=True)

        # Convert keys to string and clean
        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
        df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()

        # Build lookup from billing: {(inv, item): rtn}
        billing_lookup = {
            (row['Invoice Number'], row['Item Number']): row.get('RTN/CR No.')  # Keep dot here
            for _, row in df_billing.iterrows()
            if pd.notna(row.get('RTN/CR No.'))
        }

        # Load Firebase
        data = ref.get()
        updated = 0
        skipped = []
        not_found = []

        for key, record in data.items():
            inv = str(record.get("Invoice Number")).strip()
            item = str(record.get("Item Number")).strip()
            pair = (inv, item)

            # Check for match
            if pair in billing_lookup:
                rtn = billing_lookup[pair]
                existing_rtn = record.get("RTN/CR No")

                if not existing_rtn:  # Only update if it's missing
                    ref.child(key).update({"RTN/CR No": rtn})
                    updated += 1
                else:
                    skipped.append((inv, item, existing_rtn))
            else:
                not_found.append(pair)

        # --- Results ---
        st.success(f"✅ {updated} records updated with new RTN/CR No values.")
        if skipped:
            st.info(f"ℹ️ Skipped {len(skipped)} records (already had RTN/CR No).")
        if not_found:
            st.warning(f"⚠️ {len(not_found)} records in Firebase did not match the Billing file.")

    except Exception as e:
        st.error(f"❌ Error processing Billing Master file: {e}")
