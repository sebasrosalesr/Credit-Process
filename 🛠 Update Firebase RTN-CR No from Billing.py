import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# --- Streamlit Setup ---
st.set_page_config(page_title="RTN/CR No. Sync Tool", layout="wide")
st.title("📦 Sync RTN/CR No. from Billing Master to Firebase")

# --- Upload Billing Master ---
st.header("Step 1: Upload Billing Master Excel")
billing_file = st.file_uploader("📥 Upload Billing Master", type=["xlsx", "xls", "xlsm"])

# --- Firebase Initialization ---
if not firebase_admin._apps:
    firebase_config = dict(st.secrets["firebase"])
    firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(firebase_config)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

if billing_file:
    try:
        # Step 2: Read and Clean Billing Master File
        df_billing = pd.read_excel(billing_file, engine="openpyxl")
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number',
            'RTN/CR No.': 'RTN/CR No.'
        }, inplace=True)

        # Filter valid records
        df_billing = df_billing.dropna(subset=['Invoice Number', 'Item Number', 'RTN/CR No.'])

        # Normalize strings
        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
        df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()
        df_billing['RTN/CR No.'] = df_billing['RTN/CR No.'].astype(str).str.strip()

        # Create (Invoice, Item) → RTN/CR No. map
        billing_lookup = {
            (row['Invoice Number'], row['Item Number']): row['RTN/CR No.']
            for _, row in df_billing.iterrows()
        }

        # Step 3: Load Firebase records and apply updates
        data = ref.get()
        updated_count = 0

        for key, record in data.items():
            inv = str(record.get("Invoice Number", "")).strip()
            item = str(record.get("Item Number", "")).strip()
            existing_rtn = str(record.get("RTN_CR_No", "")).strip()  # Firebase-safe key
            pair = (inv, item)

            if not existing_rtn and pair in billing_lookup:
                ref.child(key).update({"RTN_CR_No": billing_lookup[pair]})
                updated_count += 1

        st.success(f"✅ Successfully updated {updated_count} record(s) in Firebase.")
        st.info("🔐 RTN/CR No. stored in Firebase as 'RTN_CR_No' (slash is not allowed).")
    except Exception as e:
        st.error(f"❌ Error during processing: {e}")
else:
    st.info("📄 Please upload a Billing Master file to begin.")
