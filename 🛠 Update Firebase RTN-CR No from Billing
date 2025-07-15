import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

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
st.set_page_config(page_title="🛠 Update Firebase RTN/CR No from Billing", layout="wide")
st.title("📥 Update Firebase Records Using Billing Master")
st.subheader("Upload the Billing Master Excel File")

billing_file = st.file_uploader("Drag and drop the Billing Master Excel here", type=["xlsx", "xlsm", "xls"])

if billing_file:
    try:
        # Load Billing Master
        df_billing = pd.read_excel(billing_file, engine="openpyxl")

        # Rename columns to match Firebase format
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number'
        }, inplace=True)

        # Clean and keep only necessary rows
        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip()
        df_billing['Item Number'] = df_billing['Item Number'].astype(str).str.strip()
        df_billing_clean = df_billing.dropna(subset=['RTN/CR No'])

        st.success(f"✅ Loaded {len(df_billing_clean)} billing records with RTN/CR No.")
        st.dataframe(df_billing_clean[['Invoice Number', 'Item Number', 'RTN/CR No']])

        # --- Firebase Update ---
        if st.button("📤 Update Firebase Records with RTN/CR No"):
            firebase_data = ref.get()
            updated = 0
            skipped = []
            unmatched = []

            for idx, row in df_billing_clean.iterrows():
                inv = row['Invoice Number']
                item = row['Item Number']
                rtn = row['RTN/CR No']
                matched = False

                for key, record in firebase_data.items():
                    if str(record.get("Invoice Number")) == inv and str(record.get("Item Number")) == item:
                        matched = True
                        existing_rtn = record.get("RTN/CR No")
                        if not existing_rtn:
                            ref.child(key).update({"RTN/CR No": rtn})
                            updated += 1
                        else:
                            skipped.append((inv, item, existing_rtn))
                        break

                if not matched:
                    unmatched.append((inv, item, rtn))

            st.success(f"✅ RTN/CR No added to {updated} Firebase record(s).")
            if skipped:
                st.warning(f"⚠️ Skipped {len(skipped)} records (already had RTN/CR No).")
                st.dataframe(pd.DataFrame(skipped, columns=['Invoice Number', 'Item Number', 'Existing RTN/CR No']))
            if unmatched:
                st.error(f"❌ {len(unmatched)} records not found in Firebase.")
                st.dataframe(pd.DataFrame(unmatched, columns=['Invoice Number', 'Item Number', 'RTN/CR No']))

    except Exception as e:
        st.error(f"❌ Error reading or updating data: {e}")
else:
    st.info("⬆️ Please upload the Billing Master Excel file to begin.")
