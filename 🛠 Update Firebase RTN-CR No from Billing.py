import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import time

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL_SEC = 30 * 60
MAX_ATTEMPTS = 5
LOCKOUT_SEC = 60

# =========================
# Password Gate
# =========================
def check_password():
    now = time.time()
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL_SEC:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

    if now < st.session_state["locked_until"]:
        st.error("Too many attempts. Try again in a minute.")
        st.stop()

    st.title("🔒 Private Access")
    pwd = st.text_input("Enter password:", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.update(auth_ok=True, last_seen=now, bad_attempts=0)
            st.rerun()
        else:
            st.session_state["bad_attempts"] += 1
            if st.session_state["bad_attempts"] >= MAX_ATTEMPTS:
                st.session_state["locked_until"] = now + LOCKOUT_SEC
                st.session_state["bad_attempts"] = 0
            st.error("❌ Incorrect password")
            st.stop()
    st.stop()

if not check_password():
    st.stop()

# =========================
# Streamlit Setup
# =========================
st.set_page_config(page_title="RTN/CR No. Sync Tool", layout="wide")
st.title("📦 Sync RTN/CR No. from Billing Master to Firebase")

st.header("Step 1: Upload Billing Master Excel")
billing_file = st.file_uploader("📥 Upload Billing Master", type=["xlsx", "xls", "xlsm"])

# =========================
# Firebase Initialization
# =========================
if not firebase_admin._apps:
    firebase_config = dict(st.secrets["firebase"])
    firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
    cred = credentials.Certificate(firebase_config)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://creditapp-tm-default-rtdb.firebaseio.com/'
    })

ref = db.reference('credit_requests')

# =========================
# Helper Function
# =========================
def clean_item_number(val):
    """
    Normalize Item Number:
    - Strip whitespace
    - Convert floats like 1004360.0 -> '1004360'
    - Always return as string
    """
    s = str(val).strip()
    if s.endswith(".0"):
        try:
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except ValueError:
            pass
    return s

# =========================
# Main Processing
# =========================
if billing_file:
    try:
        df_billing = pd.read_excel(billing_file, engine="openpyxl")
        df_billing.rename(columns={
            'Doc No': 'Invoice Number',
            'Item No.': 'Item Number',
            'RTN/CR No.': 'RTN/CR No.'
        }, inplace=True)

        # Drop rows missing key fields
        df_billing = df_billing.dropna(subset=['Invoice Number', 'Item Number', 'RTN/CR No.'])

        # Clean and normalize key columns
        df_billing['Invoice Number'] = df_billing['Invoice Number'].astype(str).str.strip().str.upper()
        df_billing['Item Number'] = df_billing['Item Number'].apply(clean_item_number)
        df_billing['RTN/CR No.'] = df_billing['RTN/CR No.'].astype(str).str.strip().str.upper()

        # Create (Invoice, Item) → RTN/CR No. lookup
        billing_lookup = {
            (row['Invoice Number'], row['Item Number']): row['RTN/CR No.']
            for _, row in df_billing.iterrows()
        }

        # Step 3: Sync with Firebase
        data = ref.get()
        updated_count = 0
        checked_count = 0

        for key, record in (data or {}).items():
            inv = str(record.get("Invoice Number", "")).strip().upper()
            item = clean_item_number(record.get("Item Number", ""))
            existing_rtn = str(record.get("RTN_CR_No", "")).strip().upper()
            pair = (inv, item)
            checked_count += 1

            if not existing_rtn and pair in billing_lookup:
                ref.child(key).update({"RTN_CR_No": billing_lookup[pair]})
                updated_count += 1

        st.success(f"✅ Updated {updated_count} of {checked_count} total records.")
        st.info("💾 RTN/CR No. stored in Firebase as 'RTN_CR_No' (slashes are replaced).")

    except Exception as e:
        st.error(f"❌ Error during processing: {e}")
else:
    st.info("📄 Please upload a Billing Master file to begin.")

# =========================
# Logout Button
# =========================
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()
