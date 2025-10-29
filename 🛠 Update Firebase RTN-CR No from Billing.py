import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
import time, streamlit as st

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "test123")
SESSION_TTL_SEC = 30 * 60       # 30 min
MAX_ATTEMPTS    = 5
LOCKOUT_SEC     = 60            # 1 min cooldown

def check_password():
    now = time.time()
    # init state
    st.session_state.setdefault("auth_ok", False)
    st.session_state.setdefault("last_seen", 0.0)
    st.session_state.setdefault("bad_attempts", 0)
    st.session_state.setdefault("locked_until", 0.0)

    # active session timeout
    if st.session_state["auth_ok"]:
        if now - st.session_state["last_seen"] > SESSION_TTL_SEC:
            st.session_state["auth_ok"] = False
        else:
            st.session_state["last_seen"] = now
            return True

    # lockout window after too many failures
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

# Gate the app
if not check_password():
    st.stop()

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

# Optional logout button:
if st.sidebar.button("Logout"):
    st.session_state["auth_ok"] = False
    st.rerun()
